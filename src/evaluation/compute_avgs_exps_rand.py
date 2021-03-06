import os
import sys
import caffe
import numpy as np
import lmdb
import h5py
from matplotlib import pyplot as plt
import glob

outfile = 'data/partial_siamese_rand_results.txt'

#
# get list of output files
#
slurms = glob.glob('../generate/jobs_ps_rand/*/*.log')

#
# search for minimum loss and its 
# iteration in each output file
#
min_loss = []
min_loss_iter = []
rand_stepsizes = []
rand_gammas = []
for slurm in slurms:
  loss = [] 
  iteration = []
  
  [stepsize_temp, gamma_temp] = slurm.split('/')[3].split('_')[-2:]
  rand_stepsizes.append(stepsize_temp)
  rand_gammas.append(gamma_temp)

  with open(slurm, 'r') as f:
    for line in f:
      if 'Testing net' in line:
        iteration.append(line.split()[5][:-1])
      if 'Test net output #1' in line:
        loss.append(line.split()[10])

    #min_loss.append(min(loss))
    #min_loss_iter.append(iteration[loss.index(min(loss))])
    min_loss_iter.append(iteration[-2])
    min_loss.append(loss[iteration.index(iteration[-2])])

rand_stepsizes = np.unique(rand_stepsizes)
rand_gammas = np.unique(rand_gammas)

#
# load testing dbs
#
db_name = '../testing_data/test_shuffled_im_db/'
db_labels_name = '../testing_data/test_shuffled_label_db/'

#
# load labels
#
labels = []
db_labels = lmdb.open(db_labels_name)

with db_labels.begin(write=False) as db_labels_txn:
  for (key, value) in db_labels_txn.cursor():
    label_datum = caffe.io.caffe_pb2.Datum().FromString(value)
    lbl = caffe.io.datum_to_array(label_datum)
    lbl = lbl.swapaxes(0,2).swapaxes(0,1)
    labels.append(lbl)

labels = np.vstack(labels)

#
# evaluate each network
#

count = 0
for param_1 in rand_stepsizes:
  for param_2 in rand_gammas:

    iteration = min_loss_iter[count]
    count += 1

    #
    # load the trained net 
    #
    MODEL = '../generate/jobs_ps_rand/partial_siamese_sweep_%s_%s/deploy.net' % (param_1, str(param_2).rstrip('0')) 
    PRETRAINED = '../generate/jobs_ps_rand/partial_siamese_sweep_%s_%s/snapshots/partial_siamese_iter_%s.caffemodel' % (param_1, str(param_2).rstrip('0'), iteration)
    MEAN = '../mean/transient_mean.binaryproto'

    # load the mean image 
    blob=caffe.io.caffe_pb2.BlobProto()
    file=open(MEAN,'rb')
    blob.ParseFromString(file.read())
    means = caffe.io.blobproto_to_array(blob)
    means = means[0]

    caffe.set_mode_cpu()
    net = caffe.Net(MODEL, PRETRAINED, caffe.TEST)

    #
    # process 
    #
    ix = 0
    error = np.zeros(40)
    db = lmdb.open(db_name)

    # get all keys
    with db.begin(write=False) as db_txn:
      for (key, value) in db_txn.cursor():
        im_datum = caffe.io.caffe_pb2.Datum()
        im_datum.ParseFromString(value)
        im = caffe.io.datum_to_array(im_datum)
        
        # subtract mean & resize
        caffe_input = im - means
        caffe_input = caffe_input.transpose((1,2,0))
        caffe_input = caffe.io.resize_image(caffe_input, (227,227))
        caffe_input = caffe_input.transpose((2,0,1))
        caffe_input = caffe_input.reshape((1,)+caffe_input.shape)
         
        # push through the network
        out = net.forward_all(data=caffe_input)
        pred = out['fc8-t'].squeeze()
        
        # squared difference
        error += ((pred[:] - labels[ix,:]) ** 2).squeeze()
        
        if ix % 100 == 0:
          print "Processed %d" % ix

        ix = ix + 1

    # write out to file
    error = error[:] / ix
    with open(outfile, 'a+') as f:
      f.write(str(param_1) + ' ' + str(param_2) + ' ' + str(iteration) + ' ' + str(np.average(error)) + '\n')
    print param_1, param_2, np.average(error)
