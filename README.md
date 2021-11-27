# Subspace Adversarial Training
Single-step adversarial training (AT) has received wide attention as it proved to be both efficient and robust. However, a serious problem of catastrophic overfitting exists, i.e., the robust accuracy against projected gradient descent (PGD) attack suddenly drops to 0% during the training. In this paper, we understand this problem from a novel perspective of optimization and firstly reveal the close link between the fast-growing gradient of each sample and overfitting, which can also be applied to understand the robust overfitting phenomenon in multi-step AT. To control the growth of the gradient during the training, we propose a new AT method, subspace adversarial training (Sub-AT), which constrains the AT in a carefully extracted subspace. It successfully resolves both two kinds of overfitting and hence significantly boosts the robustness. In subspace, we also allow single-step AT with larger steps and larger radius, which further improves the robustness performance. As a result, we achieve the state-of-the-art single-step AT performance: our pure single-step AT can reach over **51**% robust accuracy against strong PGD-50 attack with radius 8/255 on CIFAR-10, even surpassing the standard multi-step PGD-10 AT with huge computational advantages. 



## Dependencies

Install required dependencies:

```
pip install -r requirements.txt
```

We also evaluate the robustness with [Auto-Attack](https://github.com/fra31/auto-attack). It can be installed via following source code:

```
pip install git+https://github.com/fra31/auto-attack
```



## How to run

We show sample usages in `run.sh`:

```
bash run.sh
```

For Tiny-ImageNet experiments, please prepare the dataset first under the path `datasets/tiny-imagenet-200/`. 

For more detailed settings of different datasets, please refer to the [supplementary material](https://arxiv.org/abs/2111.12229).

