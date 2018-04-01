""" Module to expose trained models for inference."""

import tensorflow as tf

from tensorflow.contrib.learn import RunConfig
from queue import Queue
from threading import Thread

from threaded_estimator import iris_data


class FlowerEstimator:

    def __init__(self, model_path='./trained_models/',
                 threaded=True,
                 verbose=False):
        """
        Parameters
        ----------
        model_path: str
            Location from which to load the model.

        threaded: Boolean [True]
            Whether to use multi-threaded execution for inference.
            If False, the model will use a new generator for each sample that is passed to it, and reload the entire
            model each time.


        """

        (self.train_x, self.train_y), (self.test_x, self.test_y) = iris_data.load_data()
        self.batch_size = 32

        self.model_path = model_path

        self.input_queue = Queue(maxsize=1)
        self.output_queue = Queue(maxsize=1)

        self.threaded = threaded
        self.estimator = self.load_estimator()

        self.verbose = verbose

        if self.threaded:
            # We set the generator thread as daemon
            # (see https://docs.python.org/3/library/threading.html#threading.Thread.daemon)
            # This means that when all other threads are dead,
            # this thread will not prevent the Python program from exiting
            self.prediction_thread = Thread(target=self.predict_from_queue, daemon=True)
            self.prediction_thread.start()

    def generate_from_queue(self):
        """ Generator which yields items from the input queue.
        This lives within our 'prediction thread'.

        """

        while True:
            if self.verbose:
                print('Yielding from input queue')
            yield self.input_queue.get()


    def predict_from_queue(self):
        """ Adds a prediction from the model to the output_queue.

        This lives within our 'prediction thread'.

        Note: estimators accept generators as inputs and return generators as output. Here, we are
        iterating through the output generator, which will be populated in lock-step with the input
        generator.

        """

        for i in self.estimator.predict(input_fn=self.queued_predict_input_fn):
            if self.verbose:
                print('Putting in output queue')
            self.output_queue.put(i)

    def predict(self, features):
        """
        Vanilla prediction function. Converts the generator produced by the estimator into a list
        and returns the first item.

        Intended for single-shot usage.

        Parameters
        ----------
        input_str: str
            String upon which to apply estimator.predict

        Returns
        -------
        predictions: dict
            Dictionary including 'probs', 'outputs', 'predicted_class'

        """

        # Get predictions dictionary
        if self.threaded:
            features = dict(features)
            self.input_queue.put(features)
            predictions = self.output_queue.get()  # The latest predictions generator
        else:
            predictions = self.estimator.predict(input_fn=lambda: self.predict_input_fn(features))

        return predictions

    def load_estimator(self):
        """

        Returns
        -------
        estimator

        """

        # Feature columns describe how to use the input.
        my_feature_columns = []
        for key in self.train_x.keys():
            my_feature_columns.append(tf.feature_column.numeric_column(key=key))

        run_config = RunConfig()
        run_config = run_config.replace(model_dir=self.model_path)

        return tf.estimator.DNNClassifier(
            feature_columns=my_feature_columns,
            # Two hidden layers of 10 nodes each.
            hidden_units=[10, 10],
            # The model must choose between 3 classes.
            n_classes=3,
            # Use runconfig to load model,
            config=run_config,
            model_dir=self.model_path)

    def train(self, steps):

        self.estimator.train(
            input_fn=lambda: self.train_input_fn(self.train_x, self.train_y),
            steps=steps,
        )

    def train_input_fn(self, features, labels):
        """An input function for training"""

        # Convert the inputs to a Dataset.
        dataset = tf.data.Dataset.from_tensor_slices((dict(features), labels))

        # Shuffle, repeat, and batch the examples.
        dataset = dataset.shuffle(1000).repeat().batch(self.batch_size)

        # Return the dataset.
        return dataset

    def predict_input_fn(self, features):
        """An input function for prediction"""

        if self.verbose:
            print("Standard predict_input_n call")

        # Convert the inputs to a Dataset.
        dataset = tf.data.Dataset.from_tensor_slices(dict(features))
        dataset.map(self._dictify)

        # Batch the examples
        assert self.batch_size is not None, "batch_size must not be None"
        dataset = dataset.batch(self.batch_size)

        # Return the batched dataset. This is an iterator returning batches.
        return dataset

    @staticmethod
    def _dictify(input):
        return input

    def queued_predict_input_fn(self):

        if self.verbose:
            print("QUEUED INPUT FUNCTION CALLED")

        # Fetch the inputs from the input queue
        dataset = tf.data.Dataset.from_generator(self.generate_from_queue,
                                                 output_types={'SepalLength': tf.float32,
                                                               'SepalWidth': tf.float32,
                                                               'PetalLength': tf.float32,
                                                               'PetalWidth': tf.float32})

        # Return the dataset.
        return dataset

