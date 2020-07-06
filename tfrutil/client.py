# Lint as: python3

# Copyright 2020 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Provides a common interface for TFRUtil to DF Accessor and CLI.

client.py provides create_tfrecords() to upstream clients including
the Pandas DataFrame Accessor (accessor.py) and the CLI (cli.py).
"""
import logging
import os
from typing import Any, Dict, Union, Optional, Sequence

import pandas as pd
import tensorflow as tf

# from tfrutil import common
from tfrutil import constants
from tfrutil import beam_pipeline


def _validate_data(df):
  """ Verify required image csv columsn exist in data."""
  if constants.IMAGE_URI_KEY not in df.columns:
  # or label_col not in df.columns:
    raise AttributeError(
        'Dataframe must contain image_uri column {}.')
  if constants.LABEL_KEY not in df.columns:
    raise AttributeError(
        'Dataframe must contain label column.')
  if constants.SPLIT_KEY not in df.columns:
    raise AttributeError(
        'Dataframe must contain split column.')
  if list(df.columns) != constants.IMAGE_CSV_COLUMNS:
    raise AttributeError(
        'Dataframe column order must be {}'.format(
            constants.IMAGE_CSV_COLUMNS))


def _validate_runner(
    df: pd.DataFrame,
    runner: str,
    project: str,
    region: str):
  """Validates an appropriate beam runner is chosen."""
  if runner not in ['DataFlowRunner', 'DirectRunner']:
    raise AttributeError('Runner {} is not supported.'.format(runner))

  # gcs_path is a bool, true if all image paths start with gs://
  gcs_path = df[constants.IMAGE_URI_KEY].str.startswith('gs://').all()
  if (runner == 'DataFlowRunner') & (not gcs_path):
    raise AttributeError('DataFlowRunner requires GCS image locations.')

  if (runner == 'DataFlowRunner') & (
      any(not v for v in [project, region])):
    raise AttributeError('DataFlowRunner requires project region and region '
                         'project is {} and region is {}'.format(
                             project, region))

# def read_image_directory(dirpath) -> pd.DataFrame:
#   """Reads image data from a directory into a Pandas DataFrame."""
#
#   # TODO(cezequiel): Implement in phase 2.
#   _ = dirpath
#   raise NotImplementedError


def _is_directory(input_data) -> bool:
  """Returns True if `input_data` is a directory; False otherwise."""
  # TODO(cezequiel): Implement in phase 2.
  _ = input_data
  return False


def read_csv(
    csv_file: str,
    header: Optional[Union[str, int, Sequence]] = 'infer',
    names: Optional[Sequence] = None) -> pd.DataFrame:
  """Returns a a Pandas DataFrame from a CSV file."""

  if header is None and not names:
    names = constants.IMAGE_CSV_COLUMNS

  with tf.io.gfile.GFile(csv_file) as f:
    return pd.read_csv(f, names=names, header=header)


def to_dataframe(
    input_data: Union[str, pd.DataFrame],
    header: Optional[Union[str, int, Sequence]] = 'infer',
    names: Optional[Sequence] = None) -> pd.DataFrame:
  """Converts `input_data` to a Pandas DataFrame."""

  if isinstance(input_data, pd.DataFrame):
    df = input_data[names] if names else input_data

  elif isinstance(input_data, str) and input_data.endswith('.csv'):
    df = read_csv(input_data, header, names)

  elif isinstance(input_data, str) and _is_directory(input_data):
    # TODO(cezequiel): Implement in phase 2
    raise NotImplementedError

  else:
    raise ValueError('Unsupported `input_data`: {}'.format(type(input_data)))

  return df

# pylint: disable=too-many-arguments
# pylint: disable=too-many-locals

def create_tfrecords(
    input_data: Union[str, pd.DataFrame],
    output_dir: str,
    header: Optional[Union[str, int, Sequence]] = 'infer',
    names: Optional[Sequence] = None,
    runner: str = 'DirectRunner',
    project: Optional[str] = None,
    region: Optional[str] = None,
    dataflow_options: Optional[Dict[str, Any]] = None,
    job_label: str = 'create-tfrecords',
    compression: Optional[str] = 'gzip',
    num_shards: int = 0):
  """Generates TFRecord files from given input data.

  TFRUtil provides an easy interface to create image-based tensorflow records
  from a dataframe containing GCS locations of the images and labels.

  Usage:
    import tfrutil

    job_id = tfrutil.client.create_tfrecords(
        train_df,
        output_dir='gcs://foo/bar/train',
        runner='DirectFlowRunner)

  Args:
    input_data: Pandas DataFrame, CSV file or image directory path.
    output_dir: Local directory or GCS Location to save TFRecords to.
    header: Indicates row/s to use as a header. Not used when `input_data` is
      a Pandas DataFrame.
      If 'infer' (default), header is taken from the first line of a CSV
    runner: Beam runner. Can be 'DirectRunner' or 'DataFlowRunner'
    project: GCP project name (Required if DataFlowRunner)
    region: GCP region name (Required if DataFlowRunner)
    dataflow_options: Options dict for dataflow runner
    job_label: User supplied description for the beam job name.
    compression: Can be 'gzip' or None for no compression.
    num_shards: Number of shards to divide the TFRecords into. Default is
        0 = no sharding.

  """

  df = to_dataframe(input_data, header, names)

  _validate_data(df)
  _validate_runner(df, runner, project, region)
  #os.makedirs(output_dir, exist_ok=True)
  #TODO (mikebernico) this doesn't work with GCS locations...
  logfile = os.path.join('/tmp', constants.LOGFILE)
  logging.basicConfig(filename=logfile, level=constants.LOGLEVEL)
  # This disables annoying Tensorflow and TFX info/warning messages.
  logging.getLogger('tensorflow').setLevel(logging.ERROR)

  integer_label = pd.api.types.is_integer_dtype(df[constants.LABEL_KEY])
  p = beam_pipeline.build_pipeline(
      df,
      job_label=job_label,
      runner=runner,
      project=project,
      region=region,
      output_dir=output_dir,
      compression=compression,
      num_shards=num_shards,
      dataflow_options=dataflow_options,
      integer_label=integer_label)

  # TODO(mikbernico) Handle this async for the DataFlow case.
  result = p.run()
  result.wait_until_finish()
  # TODO(mikebernico) Add metrics here.
  logging.shutdown()

  # FIXME: Issue where GCSFS is not picking up the `logfile` even if it exists.
  if os.path.exists(logfile):
    pass
    # common.copy_to_gcs(logfile,
    #                    os.path.join(output_dir, constants.LOGFILE),
    #                    recursive=False)
