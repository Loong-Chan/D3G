import torch
import numpy as np
import scipy.sparse as sp
import sys
import networkx as nx
import pickle as pkl
import torch.nn.functional as F
import random


def tensor_rownorm(tensor):
    r_inv = tensor.sum(dim=1).pow(-1)
    r_inv[r_inv == float("Inf")] = 0.
    r_inv[r_inv == float("-Inf")] = 0.
    return tensor * r_inv.reshape(-1, 1)


def dgl2tensor(dglGraph, selfloop=True, rownorm=True):
    adj = dglGraph.adj().to_dense()
    adj = (adj + adj.T) / 2
    adj.diagonal().fill_(0)
    if selfloop:
        adj = adj + torch.eye(dglGraph.number_of_dst_nodes())
    if rownorm:
        adj = tensor_rownorm(adj)
    features = dglGraph.ndata["feat"]
    labels = dglGraph.ndata["label"]
    idx_train = torch.nonzero(dglGraph.ndata["train_mask"]).squeeze()
    idx_val = torch.nonzero(dglGraph.ndata["val_mask"]).squeeze()
    idx_test = torch.nonzero(dglGraph.ndata["test_mask"]).squeeze()
    return adj, features, labels, idx_train, idx_val, idx_test


def numpy_rownorm(features):
    rowsum = np.array(features.sum(1), dtype=float)
    r_inv = np.power(rowsum, -1).flatten()
    r_inv[np.isinf(r_inv)] = 0.
    r_mat_inv = sp.diags(r_inv)
    features = r_mat_inv.dot(features)
    return features


exc_path = sys.path[0]
def parse_index_file(filename):
    """Parse index file."""
    index = []
    for line in open(filename):
        index.append(int(line.strip()))
    return index


def load_data(dataset_str):
    names = ['x', 'y', 'tx', 'ty', 'allx', 'ally', 'graph']
    objects = []
    for i in range(len(names)):
        with open("{}/data/ind.{}.{}".format(exc_path, dataset_str, names[i]), 'rb') as f:
            if sys.version_info > (3, 0):
                objects.append(pkl.load(f, encoding='latin1'))
            else:
                objects.append(pkl.load(f))

    x, y, tx, ty, allx, ally, graph = tuple(objects)
    test_idx_reorder = parse_index_file("{}/data/ind.{}.test.index".format(exc_path, dataset_str))
    test_idx_range = np.sort(test_idx_reorder)

    if dataset_str == 'citeseer':
        test_idx_range_full = range(min(test_idx_reorder), max(test_idx_reorder)+1)
        tx_extended = sp.lil_matrix((len(test_idx_range_full), x.shape[1]))
        tx_extended[test_idx_range-min(test_idx_range), :] = tx
        tx = tx_extended
        ty_extended = np.zeros((len(test_idx_range_full), y.shape[1]))
        ty_extended[test_idx_range-min(test_idx_range), :] = ty
        ty = ty_extended

    features = sp.vstack((allx, tx)).tolil()
    features[test_idx_reorder, :] = features[test_idx_range, :]
    adj = nx.adjacency_matrix(nx.from_dict_of_lists(graph))
    adj = adj + adj.T.multiply(adj.T > adj) - adj.multiply(adj.T > adj)
    labels = np.vstack((ally, ty))
    labels[test_idx_reorder, :] = labels[test_idx_range, :]

    idx_test = test_idx_range.tolist()
    idx_train = range(len(y))
    idx_val = range(len(y), len(y)+500)

    adj = torch.tensor(adj.toarray())
    features = features.toarray()
    features = torch.tensor(features, dtype=torch.float32)
    labels = torch.LongTensor(labels)
    labels = torch.max(labels, dim=1)[1]
    idx_train = torch.LongTensor(idx_train)
    idx_test = torch.LongTensor(idx_test)
    idx_val = torch.LongTensor(idx_val)
    
    return adj, features, idx_train, idx_val, idx_test, labels


def normalize_features(features):
    rowsum = np.array(features.sum(1))
    r_inv = np.power(rowsum, -1).flatten()
    r_inv[np.isinf(r_inv)] = 0.
    r_mat_inv = sp.diags(r_inv)
    features = r_mat_inv.dot(features)
    return features


def accuracy(output, labels):
    preds = output.max(1)[1].type_as(labels)
    correct = preds.eq(labels).double()
    correct = correct.sum()
    return correct / len(labels)


def compute_distances_no_loops(A, B):
    m = np.shape(A)[0]
    n = np.shape(B)[0]
    M = np.dot(A, B.T)
    H = np.tile(np.matrix(np.square(A).sum(axis=1)).T,(1,n))
    K = np.tile(np.matrix(np.square(B).sum(axis=1)),(m,1))
    return np.sqrt(-2 * M + H + K)


def consis_loss(logps, temp):
    ps = [torch.exp(p) for p in logps]
    sum_p = 0.
    for p in ps:
        sum_p = sum_p + p
    avg_p = sum_p / len(ps)
    sharp_p = (torch.pow(avg_p, 1./temp) / torch.sum(torch.pow(avg_p, 1./temp), dim=1, keepdim=True)).detach()
    loss = 0.
    for p in ps:
        loss += torch.mean((p-sharp_p).pow(2).sum(1))
    loss = loss/len(ps)
    return loss
    

def set_seed(seed):
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
