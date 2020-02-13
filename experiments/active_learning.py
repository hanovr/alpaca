import sys
from collections import defaultdict
from functools import partial

import numpy as np
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split

import torch

from fastai.vision import (rand_pad, flip_lr, ImageDataBunch, Learner, accuracy, Image)
from fastai.callbacks import EarlyStoppingCallback

sys.path.append('..')
from model.cnn import AnotherConv
from model.resnet import resnet_masked
from dataloader.builder import build_dataset
from uncertainty_estimator.masks import DEFAULT_MASKS
from experiments.utils.fastai import ImageArrayDS
from active_learning.simple_update import update_set


# torch.cuda.set_device(1)
torch.backends.cudnn.benchmark = True


# Settings
val_size = 10_000
pool_size = 45_000
start_size = 4_000
step_size = 2000
steps = 20
methods = ["error_oracle", "stoch_oracle", "random", *DEFAULT_MASKS]
# methods = ["error_oracle", "random", 'l_dpp', 'AL_dpp']
epochs_per_step = 30
patience = 2
start_lr = 5e-4
weight_decay = 0.2
batch_size = 256
nn_runs = 100
model_type = 'resnet'
# model_type = 'conv'


def main():
    # Load data
    dataset = build_dataset('cifar_10', val_size=10_000)
    x_set, y_set = dataset.dataset('train')
    x_val, y_val = dataset.dataset('val')

    shape = (-1, 3, 32, 32)
    x_set = ((x_set - 128)/128).reshape(shape)
    x_val = ((x_val - 128)/128).reshape(shape)

    # Start data split
    x_set, x_train_init, y_set, y_train_init = train_test_split(x_set, y_set, test_size=start_size, stratify=y_set)
    _, x_pool_init, _, y_pool_init = train_test_split(x_set, y_set, test_size=pool_size, stratify=y_set)
    # x_pool_init, y_pool_init = x_set, y_set
    train_tfms = [*rand_pad(4, 32), flip_lr(p=0.5)]  # Transformation to augment images

    loss_func = torch.nn.CrossEntropyLoss()

    # Active learning
    val_accuracy = defaultdict(list)

    for method in methods:
        print(f"== {method} ==")
        x_pool, y_pool = np.copy(x_pool_init), np.copy(y_pool_init)
        x_train, y_train = np.copy(x_train_init), np.copy(y_train_init)

        model = build_model(model_type)

        try:
            for i in range(steps):
                print(f"Step {i+1}, train size: {len(x_train)}")
                train_ds = ImageArrayDS(x_train, y_train, train_tfms)
                val_ds = ImageArrayDS(x_val, y_val)
                data = ImageDataBunch.create(train_ds, val_ds, bs=batch_size)

                callbacks = [partial(EarlyStoppingCallback, min_delta=1e-3, patience=patience)]
                learner = Learner(data, model, metrics=accuracy, loss_func=loss_func, callback_fns=callbacks)
                learner.fit(epochs_per_step, start_lr, wd=weight_decay)

                if i != steps - 1:
                    x_pool, x_train, y_pool, y_train = update_set(
                        x_pool, x_train, y_pool, y_train, method=method, model=model)

                val_accuracy[method].append(learner.recorder.metrics[-1][0].item())
        except Exception as e:
            print(e)

    # Display results
    plot_metric(val_accuracy)


def plot_metric(metrics, title=None):
    plt.figure(figsize=(16, 9))
    title = title or f"Validation accuracy, start size {start_size}, step size {step_size}, model {model_type}"
    plt.title(title)
    for name, values in metrics.items():
        plt.plot(values, label=name)
    plt.xlabel("Steps")
    plt.ylabel("Accuracy on validation")
    plt.legend(loc='upper left')
    plt.show()


def build_model(model_type):
    if model_type == 'conv':
        model = AnotherConv()
    elif model_type == 'resnet':
        model = resnet_masked(pretrained=True)
    return model


if __name__ == '__main__':
    main()
