# Subspace Adversarial Training
Single-step adversarial training (AT) has received wide attention as it proved to be both efficient and robust. However, a serious problem of catastrophic overfitting exists, i.e., the robust accuracy against projected gradient descent (PGD) attack suddenly drops to 0% during the training. In this paper, we understand this problem from a novel perspective of optimization and firstly reveal the close link between the fast-growing gradient of each sample and overfitting, which can also be applied to understand the robust overfitting phenomenon in multi-step AT. To control the growth of the gradient during the training, we propose a new AT method, subspace adversarial training (Sub-AT), which constrains the AT in a carefully extracted subspace. It successfully resolves both two kinds of overfitting and hence significantly boosts the robustness. In subspace, we also allow single-step AT with larger steps and larger radius, which further improves the robustness performance. As a result, we achieve the state-of-the-art single-step AT performance: our pure single-step AT can reach over **51**% robust accuracy against strong PGD-50 attack with radius 8/255 on CIFAR-10, even surpassing the standard multi-step PGD-10 AT with huge computational advantages. 



## How to run

We show sample usages in `run.sh`:

```
bash run.sh
```

