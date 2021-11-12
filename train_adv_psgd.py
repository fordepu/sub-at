import argparse
import os
import shutil
import time

import torch
import torch.nn as nn
import torch.nn.parallel
import torch.backends.cudnn as cudnn
import torch.optim as optim
import torch.utils.data
import torchvision.transforms as transforms
import torchvision.datasets as datasets

from sklearn.decomposition import PCA
import matplotlib.pyplot as plt
import numpy as np
from numpy import linalg as LA
import pickle
import random
import resnet
from utils import get_datasets, get_model, epoch_adversarial, print_args, grad_align_loss, trades_loss, epoch_adversarial_PGD50, AutoAttack

from advertorch.attacks import LinfPGDAttack, L2PGDAttack
from advertorch.context import ctx_noparamgrad
from advertorch.utils import NormalizeByChannelMeanStd

def set_seed(seed=233): 
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

print ('P-SGD')

parser = argparse.ArgumentParser(description='P(+)-SGD in pytorch')
parser.add_argument('--arch', '-a', metavar='ARCH', default='resnet32',
                    help='model architecture (default: resnet32)')
parser.add_argument('--datasets', metavar='DATASETS', default='CIFAR10', type=str,
                    help='The training datasets')
parser.add_argument('-j', '--workers', default=4, type=int, metavar='N',
                    help='number of data loading workers (default: 4)')
parser.add_argument('--epochs', default=100, type=int, metavar='N',
                    help='number of total epochs to run')
parser.add_argument('--start-epoch', default=0, type=int, metavar='N',
                    help='manual epoch number (useful on restarts)')
parser.add_argument('-b', '--batch-size', default=128, type=int,
                    metavar='N', help='mini-batch size (default: 128)')
parser.add_argument('--weight-decay', '--wd', default=0.0005, type=float,
                    metavar='W', help='weight decay (default: 1e-4)')
parser.add_argument('--print-freq', '-p', default=50, type=int,
                    metavar='N', help='print frequency (default: 50)')
parser.add_argument('--resume', default='', type=str, metavar='PATH',
                    help='path to latest checkpoint (default: none)')
parser.add_argument('-e', '--evaluate', dest='evaluate', action='store_true',
                    help='evaluate model on validation set')
parser.add_argument('--pretrained', dest='pretrained', action='store_true',
                    help='use pre-trained model')
parser.add_argument('--half', dest='half', action='store_true',
                    help='use half-precision(16-bit) ')
parser.add_argument('--save-dir', dest='save_dir',
                    help='The directory used to save the trained models',
                    default='save_temp', type=str)
parser.add_argument('--save-every', dest='save_every',
                    help='Saves checkpoints at every specified number of epochs',
                    type=int, default=10)
parser.add_argument('--n_components', default=40, type=int, metavar='N',
                    help='n_components for PCA') 
parser.add_argument('--params_start', default=0, type=int, metavar='N',
                    help='which epoch start for PCA') 
parser.add_argument('--params_end', default=51, type=int, metavar='N',
                    help='which epoch end for PCA') 
parser.add_argument('--lr', default=1, type=float, metavar='N',
                    help='lr for PSGD') 
parser.add_argument('--gamma', default=0.9, type=float, metavar='N',
                    help='gamma for momentum')
parser.add_argument('--randomseed', 
                    help='Randomseed for training and initialization',
                    type=int, default=0)

########################## attack setting ##########################
parser.add_argument('--norm', default='linf', type=str, help='linf or l2')
parser.add_argument('--train_eps', default=8., type=float, help='epsilon of attack during training')
parser.add_argument('--train_step', default=10, type=int, help='itertion number of attack during training')
parser.add_argument('--train_gamma', default=2., type=float, help='step size of attack during training')
parser.add_argument('--train_randinit', action='store_false', help='randinit usage flag (default: on)')
parser.add_argument('--test_eps', default=8., type=float, help='epsilon of attack during testing')
parser.add_argument('--test_step', default=20, type=int, help='itertion number of attack during testing')
parser.add_argument('--test_gamma', default=2., type=float, help='step size of attack during testing')
parser.add_argument('--test_randinit', action='store_false', help='randinit usage flag (default: on)')

parser.add_argument('--pgd50',  action='store_true', help='evaluate the model with pgd50 (default: False)')
parser.add_argument('--autoattack', '--aa', action='store_true', help='evaluate the model with AA')
parser.add_argument('--gradalign', '--ga', action='store_true', help='gradalign term (default: False)')
parser.add_argument('--glambda', default=0.2, type=float, help='lambda for gradalign')
parser.add_argument('--tradeloss', '--trade', action='store_true', help='use tradeloss (default: False)')
parser.add_argument('--lr_max', '--learning-rate-max', default=0.3, type=float,
                    metavar='cLR', help='maximum learning rate for cyclic learning rates')

args = parser.parse_args()
set_seed(args.randomseed)
best_robust = 0
P = None

train_robust_acc = []
val_robust_acc = []
train_robust_loss = []
val_robust_loss = []
test_natural_acc = []
test_natural_loss = []
arr_time = []

print_args(args)


if args.gradalign:
    # Gradalign lambda for CIFAR-10
    arr_lambda = [0, 0.03, 0.04, 0.05, 0.06, 0.08, 0.11, 0.15, 0.20, 0.27, 0.36, 0.47, 0.63, 0.84, 1.12, 1.50, 2.00]
    args.glambda = arr_lambda[int(args.train_eps)]

train_eps = args.train_eps
args.train_eps /= 255.
args.train_gamma /= 255.
args.test_eps /= 255.
args.test_gamma /= 255.

def get_model_param_vec(model):
    """
    Return model parameters as a vector
    """
    vec = []
    for name,param in model.named_parameters():
        vec.append(param.detach().cpu().numpy().reshape(-1))
    return np.concatenate(vec, 0)

def get_model_grad_vec(model):
    # Return the model grad as a vector

    vec = []
    for name,param in model.named_parameters():
        vec.append(param.grad.detach().reshape(-1))
    return torch.cat(vec, 0)

def update_grad(model, grad_vec):
    idx = 0
    for name,param in model.named_parameters():
        arr_shape = param.grad.shape
        size = 1
        for i in range(len(list(arr_shape))):
            size *= arr_shape[i]
        param.grad.data = grad_vec[idx:idx+size].reshape(arr_shape)
        idx += size

def main():

    global args, best_robust, P, arr_time, train_eps

    # Check the save_dir exists or not
    print (args.save_dir)
    if not os.path.exists(args.save_dir):
        os.makedirs(args.save_dir)
    
    # Define model
    model = torch.nn.DataParallel(get_model(args))
    model.cuda()

    # Load sampled model parameters
    print ('params: from', args.params_start, 'to', args.params_end)
    W = []
    for i in range(args.params_start, args.params_end):
        ############################################################################
        # if i % 2 != 0: continue

        model.load_state_dict(torch.load(os.path.join(args.save_dir,  str(i) +  '.pt')))
        W.append(get_model_param_vec(model))
    W = np.array(W)
    print ('W:', W.shape)

    # Obtain base variables through PCA
    pca = PCA(n_components=args.n_components)
    pca.fit_transform(W)
    P = np.array(pca.components_)
    print ('ratio:', pca.explained_variance_ratio_)
    print ('P:', P.shape)

    P = torch.from_numpy(P).cuda()

    # Resume from params_start
    model.load_state_dict(torch.load(os.path.join(args.save_dir,  str(args.params_start) +  '.pt')))

    # Prepare Dataloader
    train_loader, val_loader, test_loader = get_datasets(args)

    
    # Define loss function (criterion) and optimizer
    criterion = nn.CrossEntropyLoss().cuda()
    if args.half:
        model.half()
        criterion.half()

    cudnn.benchmark = True

    optimizer = optim.SGD(model.parameters(), lr=args.lr, momentum=0.9)
    lr_scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer,
                                                        milestones=[50], last_epoch=args.start_epoch - 1)

    if args.evaluate:
        validate(val_loader, model, criterion)
        return

    end = time.time()

    is_best = 0
    print ('Start training: ', args.start_epoch, '->', args.epochs)
    
    print ('grad_algin:', args.gradalign)
    if args.gradalign:
        print ('lambda:', args.glambda)

    print ('tradeloss:', args.tradeloss)

    nat_last5 = []
    rob_last5 = []

    for epoch in range(args.start_epoch, args.epochs):

        # train for one epoch
        print('current lr {:.5e}'.format(optimizer.param_groups[0]['lr']))
        train(train_loader, model, criterion, optimizer, epoch)
        lr_scheduler.step()

        # evaluate on validation set
        natural_acc = validate(test_loader, model, criterion)
        # validate(train_loader, model, criterion)

        torch.save(model.state_dict(), os.path.join(args.save_dir, 'train' + str(train_eps) + 'psgd_' + str(epoch) + '.pt'))

        # if args.datasets == 'TinyImagenet':
        #     continue

        # evaluate the adversarial robustness on validation set
        robust_acc, adv_loss = epoch_adversarial(val_loader, model, args)
        val_robust_acc.append(robust_acc)
        val_robust_loss.append(adv_loss)
        print ('adv acc on validation set', robust_acc)

        # remember best prec@1 and save checkpoint
        is_best = robust_acc > best_robust
        best_robust = max(robust_acc, best_robust)

        if epoch + 5 >= args.epochs:
            nat_last5.append(natural_acc)        
            robust_acc, adv_loss = epoch_adversarial(test_loader, model, args)
            print ('adv acc on test set', robust_acc)
            rob_last5.append(robust_acc)

        if is_best:
            torch.save(model.state_dict(), os.path.join(args.save_dir, 'train' + str(train_eps) + 'psgd_best.pt'))


    print ('train_robust_acc: ', train_robust_acc)
    print ('train_robust_loss: ', train_robust_loss)
    print ('val_robust_acc: ', val_robust_acc)
    print ('val_robust_loss: ', val_robust_loss)
    print ('test_natural_acc: ', test_natural_acc)
    print ('test_natural_loss: ', test_natural_loss)
    print ('total training time: ', np.sum(arr_time))    

    print ('last:')
    torch.save(model.state_dict(), os.path.join(args.save_dir, 'train' + str(train_eps) + 'psgd_last.pt'))
    print ('last 5 adv acc on test dataset:', np.mean(rob_last5))
    print ('last 5 nat acc on test dataset:', np.mean(nat_last5))

    del P
    torch.cuda.empty_cache()
    if args.pgd50:
        epoch_adversarial_PGD50(test_loader, model)
    if args.autoattack:
        AutoAttack(model, dataset=args.datasets)

    print ('best:')
    model.load_state_dict(torch.load(os.path.join(args.save_dir, 'train' + str(train_eps) + 'psgd_best.pt')))
    robust_acc, adv_loss = epoch_adversarial(test_loader, model, args)
    print ('best adv acc on test dataset:', robust_acc)
    torch.cuda.empty_cache()
    if args.pgd50:
        epoch_adversarial_PGD50(test_loader, model)
    if args.autoattack:
        AutoAttack(model, dataset=args.datasets)

    validate(test_loader, model, criterion)

running_grad = 0

def train(train_loader, model, criterion, optimizer, epoch):
    # Run one train epoch

    global P, train_robust_acc, train_robust_loss, args, arr_time
    
    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()
    top1 = AverageMeter()

    if args.norm == 'linf':
        adversary = LinfPGDAttack(
            model, loss_fn=criterion, eps=args.train_eps, nb_iter=args.train_step, eps_iter=args.train_gamma,
            rand_init=args.train_randinit, clip_min=0.0, clip_max=1.0, targeted=False
        )
    elif args.norm == 'l2':
        adversary = L2PGDAttack(
            model, loss_fn=criterion, eps=args.train_eps, nb_iter=args.train_step, eps_iter=args.train_gamma,
            rand_init=args.train_randinit, clip_min=0.0, clip_max=1.0, targeted=False
        )  

    # Switch to train mode
    model.train()

    end = time.time()
    for i, (input, target) in enumerate(train_loader):

        # Measure data loading time
        data_time.update(time.time() - end)

        # Load batch data to cuda
        target = target.cuda()
        input_var = input.cuda()
        target_var = target
        if args.half:
            input_var = input_var.half()

        if args.tradeloss:
            # calculate robust loss
            output, loss = trades_loss(model=model,
                            x_natural=input_var,
                            y=target_var,
                            optimizer=optimizer,
                            step_size=args.train_gamma,
                            epsilon=args.train_eps,
                            perturb_steps=args.train_step,
                            beta=6.0)
        else:
            #adv samples
            with ctx_noparamgrad(model):
                input_adv = adversary.perturb(input_var, target_var)

            # Compute output
            output = model(input_adv)
            loss = criterion(output, target_var)

            if args.gradalign:
                loss += grad_align_loss(model, input_var, target_var, args)

        # Compute gradient and do SGD step
        optimizer.zero_grad()
        loss.backward()

        # Do P_SGD update
        gk = get_model_grad_vec(model)
        P_SGD(model, optimizer, gk)

        # Measure accuracy and record loss
        prec1 = accuracy(output.data, target)[0]
        losses.update(loss.item(), input.size(0))
        top1.update(prec1.item(), input.size(0))

        # Measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()
        
        if i % args.print_freq == 0 or i == len(train_loader)-1:
            print('Epoch: [{0}][{1}/{2}]\t'
                  'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                  'Data {data_time.val:.3f} ({data_time.avg:.3f})\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Prec@1 {top1.val:.3f} ({top1.avg:.3f})'.format(
                      epoch, i, len(train_loader), batch_time=batch_time,
                      data_time=data_time, loss=losses, top1=top1))
        
    train_robust_loss.append(losses.avg)
    train_robust_acc.append(top1.avg)
    arr_time.append(batch_time.sum)


def P_SGD(model, optimizer, grad):
    # P_plus_BFGS algorithm

    gk = torch.mm(P, grad.reshape(-1,1))

    grad_proj = torch.mm(P.transpose(0, 1), gk)
    # grad_res = grad - grad_proj.reshape(-1)

    # Update the model grad and do a step
    update_grad(model, grad_proj)
    optimizer.step()

def validate(val_loader, model, criterion):
    # Run evaluation

    global test_natural_acc, test_natural_loss  

    batch_time = AverageMeter()
    losses = AverageMeter()
    top1 = AverageMeter()

    # Switch to evaluate mode
    model.eval()

    end = time.time()
    with torch.no_grad():
        for i, (input, target) in enumerate(val_loader):
            target = target.cuda()
            input_var = input.cuda()
            target_var = target.cuda()

            if args.half:
                input_var = input_var.half()

            # Compute output
            output = model(input_var)
            loss = criterion(output, target_var)

            output = output.float()
            loss = loss.float()

            # Measure accuracy and record loss
            prec1 = accuracy(output.data, target)[0]
            losses.update(loss.item(), input.size(0))
            top1.update(prec1.item(), input.size(0))

            # Measure elapsed time
            batch_time.update(time.time() - end)
            end = time.time()

            if i % args.print_freq == 0:
                print('Test: [{0}/{1}]\t'
                      'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                      'Prec@1 {top1.val:.3f} ({top1.avg:.3f})'.format(
                          i, len(val_loader), batch_time=batch_time, loss=losses,
                          top1=top1))

    print(' * Prec@1 {top1.avg:.3f}'
          .format(top1=top1))

    # Store the test loss and test accuracy
    test_natural_loss.append(losses.avg)
    test_natural_acc.append(top1.avg)

    return top1.avg

def save_checkpoint(state, is_best, filename='checkpoint.pth.tar'):
    # Save the training model

    torch.save(state, filename)

class AverageMeter(object):
    # Computes and stores the average and current value

    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count


def accuracy(output, target, topk=(1,)):
    # Computes the precision@k for the specified values of k

    maxk = max(topk)
    batch_size = target.size(0)

    _, pred = output.topk(maxk, 1, True, True)
    pred = pred.t()
    correct = pred.eq(target.view(1, -1).expand_as(pred))

    res = []
    for k in topk:
        correct_k = correct[:k].view(-1).float().sum(0)
        res.append(correct_k.mul_(100.0 / batch_size))
    return res

if __name__ == '__main__':
    main()
