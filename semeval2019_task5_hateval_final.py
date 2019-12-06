# -*- coding: utf-8 -*-
"""SemEval2019_Task5_Hateval_Final.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1qVsQkAUB9Z1BSi3ClkTb9s1q_ZwYXoXy

# SemEval 2019 Task 5 - Shared Task on Multilingual Detection of Hate

[CodaLab Competion website](https://competitions.codalab.org/competitions/19935)

[Reference](https://www.aclweb.org/anthology/S19-2088/)

## How to run

Update the parameter in `TrainParameters` as needed to switch between different settings.

## Author
- Yonael Bekele
- Michael Lin
- Helen Zhao

### Notes
We cached pre-trained models and stuffs on Google Drive, you will need access to our team drive to run the code.
Also, this notebook is meant to be run in Colab.

## Import libraries and utility methods
"""

# built-in libs
import os
import re
import sys
import time
import csv
from datetime import datetime

# pytorch stuffs
import torch
import torchtext
import torch.nn as nn
import torch.nn.functional as F

# nltk
import nltk
from nltk import word_tokenize

# sklearn
import sklearn

# numpy
import numpy as np

# config
PROJECT_ROOT_PATH = "./"
LANG = "en"
SPACY_CONFIG = {
    "en": {
        "path": os.path.join(PROJECT_ROOT_PATH, "en_core_web_lg-2.2.0/en_core_web_lg/en_core_web_lg-2.2.0")
    }
}
CKPT_PATH = {
    "en": {
        "path": os.path.join(PROJECT_ROOT_PATH, "checkpoints/en/")
    }
}
OUTPUT_PATH = {
    "en": {
        "path": os.path.join(PROJECT_ROOT_PATH, "output/en/")
    }
}
DEBUG = True

# create output path
if not os.path.isdir(OUTPUT_PATH[LANG]["path"]):
    os.makedirs(OUTPUT_PATH[LANG]["path"])

def tokenizer(text):
    # https://stackoverflow.com/questions/13896056/how-to-remove-user-mentions-and-urls-in-a-tweet-string-using-python
    # step 1 & 3: remove mentions and url
    clean_row = re.sub(r"(?:\@|https?\://)\S+", "", text)

    # step 5: extracting words from hashtags using pascal case
    # regex expression: https://stackoverflow.com/questions/1128305/regex-for-pascalcased-words-aka-camelcased-with-leading-uppercase-letter - Nicolas Henneaux solution
    pascal = re.findall(r"[A-Z][a-z0-9]*[A-Z0-9][a-z0-9]+[A-Za-z0-9]*", clean_row)
    for p in pascal:
        # p_text = p.replace('#','')
        re_content = re.findall("[A-Z][^A-Z]*", p)
        extracted = " ".join(re_content)
        clean_row = re.sub("#" + p, extracted, clean_row)
    # step 2: remove punctuation + non-alphanumericals
    final_clean = re.sub(r"[^A-Za-z0-9\']+", " ", clean_row)

    # step 4: Contracting whitespace
    tokens = word_tokenize(str(final_clean.strip().lower()))
    return tokens

nltk.download('punkt')

print('Python version:', sys.version)
print("NLTK version {}".format(nltk.__version__))
print("PyTorch version {}".format(torch.__version__))
print('Torch Text version:', torchtext.__version__)

"""## Load data"""

# Data field
ID = torchtext.data.Field(sequential=False, use_vocab=False)
# TEXT.reverse() to get original text from encoded text
TEXT = torchtext.data.ReversibleField(sequential=True, tokenize=tokenizer, include_lengths=True, lower=True)
HS_LABEL = torchtext.data.Field(
    sequential=False, use_vocab=False, is_target=True, pad_token=None, unk_token=None
)
TR_LABEL = torchtext.data.Field(
    sequential=False, use_vocab=False, is_target=True, pad_token=None, unk_token=None
)
AG_LABEL = torchtext.data.Field(
    sequential=False, use_vocab=False, is_target=True, pad_token=None, unk_token=None
)

class BatchGenerator:
    def __init__(self, dl, x_var, y_vars):
        self.dl, self.x_var, self.y_vars = (
            dl,
            x_var,
            y_vars,
        )

    def __iter__(self):
        for batch in self.dl:
            x = getattr(batch, self.x_var)
            if self.y_vars is not None:
                y = torch.cat(
                    [getattr(batch, feat).unsqueeze(1) for feat in self.y_vars], dim=1
                ).float()
            else:
                y = torch.zeros((1))

            yield (x[0], y)

    def __len__(self):
        return len(self.dl)

def load_data(lang, device, config, label, use_pretrained=False):
    train_data, validation_data, test_data = torchtext.data.TabularDataset.splits(
        path=os.path.join(PROJECT_ROOT_PATH, "dataset"),
        train="hs-{}.tsv.train".format(lang),
        validation="hs-{}.tsv.dev".format(lang),
        test="hs-{}.tsv.test".format(lang),
        format="tsv",
        skip_header=True,
        fields=[
            ("id", ID),
            ("text", TEXT),
            ("HS", HS_LABEL),
            ("TR", TR_LABEL),
            ("AG", AG_LABEL),
        ],
    )

    print("Data Summary: Train: {}, Validation: {}, Test: {}".format(len(train_data), len(validation_data), len(test_data)))

    if use_pretrained:
        TEXT.build_vocab(train_data, vectors="glove.twitter.27B.200d", vectors_cache=os.path.join(PROJECT_ROOT_PATH, ".vector_cache/"))
    else:
        TEXT.build_vocab(train_data)
    HS_LABEL.build_vocab(train_data)
    AG_LABEL.build_vocab(train_data)
    TR_LABEL.build_vocab(train_data)

    train_dataloader, validation_dataloader = torchtext.data.BucketIterator.splits(
        (train_data, validation_data),
        batch_sizes=(config.batch_size, config.batch_size),
        device=device,
        sort_key=lambda x: len(x.text),
        sort_within_batch=False,
        repeat=False,
    )
    test_dataloader = torchtext.data.Iterator(test_data, batch_size=config.test_batch_size, device=device, sort=False, sort_within_batch=False, repeat=False)

    train_iter = BatchGenerator(train_dataloader, "text", label)
    validation_iter = BatchGenerator(validation_dataloader, "text", label)
    test_iter = BatchGenerator(test_dataloader, "text", label)

    return train_iter, validation_iter, test_iter

"""## Hyperparameters"""

class HyperParameters(object):
    def __init__(self):
        self.learning_rate = 0.0005
        self.num_epochs = 100
        self.momentum = 0
        self.batch_size = 16
        self.test_batch_size = 32
        self.embedding_dim = 128

"""## NN Models"""

class Net(nn.Module):
    def __init__(self, num_embeddings, embedding_dim, batch_size, label=None):
        super(Net, self).__init__()
        print("Num embedding: {}, Embedding dim: {}, Batch size: {}".format(num_embeddings, embedding_dim, batch_size))
        self.batch_size = batch_size
        self.embed = nn.Embedding(num_embeddings, embedding_dim)
        self.lstm = nn.LSTM(embedding_dim, 64, num_layers=2, dropout=0.5, bidirectional=True, batch_first=True)
        self.fc = nn.Linear(in_features=64, out_features=2)
        if label != None:
          self.set_initial_weights(label)

        # if pretrained_weights:
        #     self.emb.weight.data.copy_(pretrained_vec)

    def set_initial_weights(self, label):
        if label[0] == "HS":
          vocab = HS_LABEL.vocab
        elif label[0] == "TR":
          vocab = TR_LABEL.vocab
        elif label[0] == "AG":
          vocab = AG_LABEL.vocab

        tensor = torch.tensor((1,64), dtype=torch.float)
        weights = nn.Parameter(torch.cat((tensor.new_full((1,64), 1/vocab.freqs["0"]), tensor.new_full((1,64), 1/vocab.freqs["1"])), 0), requires_grad=True)
        assert weights.shape == self.fc.weight.shape

        with torch.no_grad():
            self.fc.weight = weights

    def forward(self, x):
        x = x.transpose(0, 1)
        batch_size = x.shape[0]
        x = self.embed(x)
        x, (h_n, _) = self.lstm(x)
        # get the hidden state of the last layer
        x = self.fc(h_n[-1])
        return x

class NetGlove(nn.Module):
    def __init__(self, num_embeddings, embedding_dim, batch_size, pretrained_weights=None):
        super(NetGlove, self).__init__()
        print("Num embedding: {}, Embedding dim: {}, Batch size: {}".format(num_embeddings, embedding_dim, batch_size))
        self.batch_size = batch_size
        self.embed = nn.Embedding(num_embeddings, embedding_dim)
        self.lstm = nn.LSTM(embedding_dim, 64, num_layers=2, dropout=0.5, bidirectional=True, batch_first=True)
        self.fc = nn.Linear(in_features=64, out_features=2)

        if pretrained_weights is not None:
            self.embed.weight.data.copy_(pretrained_weights)

    def set_initial_weights(self, label):
        if label[0] == "HS":
          vocab = HS_LABEL.vocab
        elif label[0] == "TR":
          vocab = TR_LABEL.vocab
        elif label[0] == "AG":
          vocab = AG_LABEL.vocab

        tensor = torch.tensor((1,64), dtype=torch.float)
        weights = nn.Parameter(torch.cat((tensor.new_full((1,64), 1/vocab.freqs["0"]), tensor.new_full((1,64), 1/vocab.freqs["1"])), 0), requires_grad=True)
        assert weights.shape == self.fc.weight.shape

        with torch.no_grad():
            self.fc.weight = weights

    def forward(self, x):
        x = x.transpose(0, 1)
        batch_size = x.shape[0]
        x = self.embed(x)
        x, (h_n, _) = self.lstm(x)
        # get the hidden state of the last layer
        x = self.fc(h_n[-1])
        return x

"""## Training and stuffs"""

def train(model, criterion, optimizer, train_data, validation_data, vocabs, device, config, params, last_epoch=1, last_max_valid_acc=0, last_min_valid_loss=1000):
    model.train()

    train_correct = 0
    train_total = 0
    max_valid_acc = last_max_valid_acc
    min_valid_loss = last_min_valid_loss

    total_train_acc = 0
    total_valid_acc = 0
    for epoch in range(last_epoch, config.num_epochs + 1):
        running_loss = 0
        for text, target in train_data:
            text = text.to(device)
            target = torch.tensor([t[0] for t in target.tolist()], dtype=torch.long).to(device)

            optimizer.zero_grad()
            outputs = model(text)
            loss = criterion(outputs, target)
            loss.backward()
            optimizer.step()

            pred = torch.max(outputs, 1)[1]
            train_correct += pred.eq(target.data.view_as(pred)).cpu().sum()
            train_total += target.size(0)
            running_loss += loss.item()
        epoch_loss = running_loss / len(train_data)
        train_accuracy = train_correct.data.cpu().numpy() / train_total
        total_train_acc += train_accuracy
        # validation after each epoch
        validation_accuracy, validation_loss, _ = eval(model, criterion, validation_data, device)
        total_valid_acc += validation_accuracy
        print("Epoch: {}, Training Loss: {:.4f}, Validation Loss: {:.4f}, Train Acc: {:.3f}%, Validation Acc: {:.3f}%".format(
            epoch,
            epoch_loss,
            validation_loss,
            train_accuracy * 100,
            validation_accuracy * 100
        ))

        if validation_accuracy > max_valid_acc:
            model_dict = {
                'model': model.state_dict(),
                'optimizer': optimizer.state_dict(),
                'train_loss': epoch_loss,
                'train_acc': train_accuracy,
                'valid_loss': validation_loss,
                'valid_acc': validation_accuracy,
                'epoch': epoch,
                'timestamp': datetime.now().strftime("%y/%m/%d %H:%M:%S"),
            }
            save_ckpt(model_dict, os.path.join(CKPT_PATH[LANG]["path"], params.ckpt_dir), "model.pt.{:d}".format(epoch))
            max_valid_acc = validation_accuracy
        model.train()
    print(f"Total epoch: {config.num_epochs}, Avg Train Acc: {(total_train_acc / config.num_epochs * 100):.3f}%, Avg Valid Acc: {(total_valid_acc / config.num_epochs * 100):.3f}%")
    return model

def eval(model, criterion, validation_data, device):
    model.eval()
    validation_loss = 0
    correct = 0
    total = 0
    gold_labels = []
    pred_labels = []
    ids = []
    with torch.no_grad():
        for data, target in validation_data:
            data = data.to(device)
            ids += [t[1] for t in target.tolist()]
            target = torch.tensor([t[0] for t in target.tolist()], dtype=torch.long).to(device)
            output = model(data)
            validation_loss += criterion(output, target).item()
            pred = output.data.max(1, keepdim=True)[1]
            correct += pred.eq(target.data.view_as(pred)).cpu().sum()
            total += target.size(0)
            # save labels
            gold_labels += list(target.int())
            pred_labels += list(pred.data.int().cpu())
    validation_loss /= len(validation_data)
    return correct.data.cpu().numpy() / total, validation_loss, (gold_labels, pred_labels, ids)

def save_ckpt(ckpt, ckpt_dir, ckpt_name):
    if not os.path.isdir(ckpt_dir):
        os.makedirs(ckpt_dir)
    torch.save(ckpt, os.path.join(ckpt_dir, ckpt_name))

def load_best_model(device, params):
    weights_dir = os.path.join(CKPT_PATH[LANG]["path"], params.ckpt_dir)
    matching_ckpts = [k for k in os.listdir(weights_dir) if
                      os.path.isfile(os.path.join(weights_dir, k))]
    if not matching_ckpts:
        msg = "No checkpoints found in {}".format(weights_dir)
        if params.load_ckpt == 1:
            raise IOError(msg)
        print(msg)
    else:
       matching_ckpts.sort(key=lambda x: [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', x)])
       ckpt_path = os.path.join(weights_dir, matching_ckpts[-1])
       print("Loading checkpoint from: {}".format(ckpt_path))
       return torch.load(ckpt_path, map_location=device)

class TrainParameters:
    def __init__(self):
        """
        :ivar load_ckpt
            0: train from scratch
            1: load and test
            2: load if exists and continue training
        :ivar task
            0: HS
            1: TR
            2: AG
        :ivar use_pretrained
            True: use pre-trained glove model glove.twitter.27b.200d
            False: do not use any pre-trained model
        """
        self.load_ckpt = 0
        self.task = 0
        self.use_pretrained = False
        self.use_balanced_weight = False

        if self.task == 0:
            self.label = ["HS", "id"]
            self.output_name = "en_a.tsv"
            self.ckpt_dir = "task_1/"

        elif self.task == 1:
            self.label = ["TR", "id"]
            self.output_name = "en_b.tsv"
            self.ckpt_dir = "task_2/"

        elif self.task == 2:
            self.label = ["AG", "id"]
            self.output_name = "en_c.tsv"
            self.ckpt_dir = "task_3/"

print("CUDA Available: ", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU Info: {}".format(torch.cuda.get_device_name()))
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# config
config = HyperParameters()
# training params
params = TrainParameters()

# load data into dataloader
train_data, validation_data, test_data = load_data(lang=LANG, device=device, config=config, label=params.label, use_pretrained=params.use_pretrained)
print(len(TEXT.vocab))

if params.use_pretrained and not params.use_balanced_weight:
    # only pre-trained weight
    config.embedding_dim = 200
    model = NetGlove(len(TEXT.vocab), config.embedding_dim, config.batch_size, pretrained_weights=TEXT.vocab.vectors).to(device)
elif params.use_balanced_weight and not params.use_pretrained:
    # only balanced weight
    config.embedding_dim = 128
    model = Net(len(TEXT.vocab), config.embedding_dim, config.batch_size, label=params.label).to(device)
elif not params.use_balanced_weight and not params.use_pretrained:
    # none
    config.embedding_dim = 128
    model = Net(len(TEXT.vocab), config.embedding_dim, config.batch_size, label=params.label).to(device)
else:
    raise Exception("Not supported!")

criterion = nn.CrossEntropyLoss().to(device)
optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)

print("Train Config Summay")
print(f"Use pre-trained weight: {params.use_pretrained}, Use balanced weight: {params.use_balanced_weight}, Task: {params.task}, Load ckpt: {params.load_ckpt}")

# load last checkpoint
if params.load_ckpt == 1 or params.load_ckpt == 2:
    ckpt = load_best_model(device, params)
    if ckpt:
        model.load_state_dict(ckpt["model"])
        optimizer.load_state_dict(ckpt["optimizer"])
        last_epoch = int(ckpt["epoch"])
        max_valid_acc = ckpt["valid_acc"]
        min_valid_loss = ckpt["valid_loss"]
        print(max_valid_acc)
        print(min_valid_loss)
    else:
        last_epoch = 0
        max_valid_acc = 0

if params.load_ckpt == 2:
    # continue training
    train(model, criterion, optimizer, train_data, validation_data, TEXT.vocab, device, config, params, last_epoch=last_epoch+1, last_max_valid_acc=max_valid_acc, last_min_valid_loss=min_valid_loss)
elif params.load_ckpt == 0:
    # start from stratch
    train(model, criterion, optimizer, train_data, validation_data, TEXT.vocab, device, config, params)

print("Testing...")
start_t = time.time()
test_accuracy, test_loss, (gold_labels, pred_labels, ids) = eval(model, criterion, test_data, device)
end_t = time.time()
test_time = end_t - start_t

# convert tensor to regular python datatype
ids = list(map(int, ids))
gold_labels = list(map(lambda x: x.item(), gold_labels))
pred_labels = list(map(lambda x: x.item(), pred_labels))

# save output to tsv
tsv_path = os.path.join(OUTPUT_PATH[LANG]["path"], params.output_name)
with open(tsv_path, "wt") as output_file:
    tsv_writer = csv.writer(output_file, delimiter="\t")
    tsv_writer.writerows(zip(ids, pred_labels))

# f1_score = sklearn.metrics.f1_score(gold_labels, pred_labels)
precision, recall, f1_score, _ = sklearn.metrics.precision_recall_fscore_support(gold_labels, pred_labels, average='binary')
print(f'Test Loss: {test_loss:.6f}, Test Acc: {test_accuracy*100:.3f}%, Test Time: {test_time:.3f} sec')
print(f"F1 Score: {f1_score}, Precision: {precision:.3f}, Recall: {recall:.3f}")