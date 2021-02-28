import os
from typing import List, Dict, Union, Optional, Callable
from functools import partial
from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    TrainingArguments,
    Trainer,
    DataCollatorWithPadding
)
from transformers.tokenization_utils import (
    PreTrainedTokenizer,
)
from .auto import (
    AutoModelForMultiLabelSequenceClassification,
)
from .conf import (
    Task,
)
from .datasets import (
    SequenceClassificationDataset,
    TokenClassificationDataset,
)
from .metrics import (
    classification_metrics,
    multilabel_classification_metrics,
)

AIRESEARCH_MODEL_PREFIX = 'airesearch/wangchanberta'
AIRESEARCH_MODEL_NAME = {
    f'{AIRESEARCH_MODEL_PREFIX}-base-att-spm-uncased': {
        'space_token': '<_>'
    }
}

FINETUNE_SEQ_CLS_METRIC_MAPPING = {
    Task.MULTICLASS_CLS.value: classification_metrics,
    Task.MULTILABEL_CLS.value: multilabel_classification_metrics
}

FINETUNE_SEQ_CLS_MODEL_MAPPING = {
    Task.MULTICLASS_CLS.value: AutoModelForSequenceClassification,
    Task.MULTILABEL_CLS.value: AutoModelForMultiLabelSequenceClassification
}


class BaseFinetuner:

    def load_pretrained_tokenizer(self):
        pass

    def load_pretrained_model(self):
        pass

    def finetune(self):
        pass


class SequenceClassificationFinetuner:

    def __init__(self,
                 tokenizer: PreTrainedTokenizer = None,
                 config=None,
                 task: Union[str, Task] = None,
                 num_labels: int = None,
                 metric: Union[str, Callable, Task] = None):

        self.tokenizer = tokenizer
        self.config = config
        self.task = task.value if type(task) == Task else task
        self.num_labels = num_labels
        self.metric = metric
        self.training_args = None
        self.trainer = None

    def load_pretrained_tokenizer(self,
                                  tokenizer_cls: PreTrainedTokenizer,
                                  name_or_path: Union[str, os.PathLike]):
        """
        Load a pretrained tokenizer to the finetuner instance
        """

        self.tokenizer = tokenizer_cls.from_pretrained(name_or_path)

        if tokenizer_cls.__name__ == 'CamembertTokenizer':

            if name_or_path in AIRESEARCH_MODEL_NAME.keys():

                self.tokenizer.additional_special_tokens = [
                    '<s>NOTUSED',
                    '</s>NOTUSED',
                    AIRESEARCH_MODEL_NAME[name_or_path]['space_token']
                ]

    def load_pretrained_model(self,
                              task: Union[str, Task],
                              name_or_path: Union[str, os.PathLike],
                              num_labels: int = None):
        """
        Load a pretrained model to the finetuner instance and modify classification head
        and metric according to the specified `task` in the method argument.

        Arguments:
            task: Union[str, Task],
        """
        if num_labels == None:
            self.config = AutoConfig.from_pretrained(name_or_path)
        else:
            self.config = AutoConfig.from_pretrained(
                name_or_path,
                num_labels=num_labels
            )

        if type(task) == Task:
            task = task.value

        self.task = task

        if task not in FINETUNE_SEQ_CLS_MODEL_MAPPING.keys():
            raise NotImplementedError(
                f"The task specified `{task}` is incorrect or not available for {self.__class__.__name__}")

        self.model = FINETUNE_SEQ_CLS_MODEL_MAPPING[task].from_pretrained(name_or_path,
                                                                          config=self.config)
        self.metric = FINETUNE_SEQ_CLS_METRIC_MAPPING[task]
        if task == Task.MULTILABEL_CLS.value:
            self.metric = partial(self.metric, n_labels=num_labels)

    def _init_trainer(self,
                      training_args,
                      train_dataset: SequenceClassificationDataset,
                      val_dataset: SequenceClassificationDataset = None):

        self.training_args = training_args
        data_collator = DataCollatorWithPadding(self.tokenizer,
                                                padding=True,
                                                pad_to_multiple_of=8 if training_args.fp16 else None)

        self.trainer = Trainer(
            model=self.model,
            args=self.training_args,
            compute_metrics=self.metric,
            train_dataset=train_dataset,
            eval_dataset=val_dataset,
            data_collator=data_collator
        )

    def finetune(self,
                 training_args,
                 train_dataset: SequenceClassificationDataset,
                 val_dataset: SequenceClassificationDataset = None,
                 test_dataset: SequenceClassificationDataset = None):

        self._init_trainer(
            training_args=training_args,
            train_dataset=train_dataset,
            val_dataset=val_dataset
        )
        self.trainer.train()
        self.trainer.save_model(
            os.path.join(training_args.output_dir,
                         'checkpoint-final')
        )

        if test_dataset != None:

            _, label_ids, result = self.trainer.predict(
                test_dataset=test_dataset)

            print(f'Evaluation on test set')

            for key, value in result.items():
                print(f'{key} : {value:.4f}')

            return result
