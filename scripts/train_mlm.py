import torch
import os
import logging


import glob
from dataclasses import dataclass, field
from typing import Optional, List, Dict

import numpy as np
import transformers
from transformers import (
    AutoConfig,
    AutoTokenizer,
    AutoModelForMaskedLM,
    DataCollatorForLanguageModeling,
    HfArgumentParser,
    Trainer,
    TrainingArguments,
    set_seed,
)

#thai2transformers
from thai2transformers.datasets import MLMDataset

logger = logging.getLogger(__name__)

@dataclass
class ArchitectureArguments:
    architecture: str = field(
        default='roberta-base',
        metadata={'help': 'Name of architecture to be pre-trained.'}
    )


@dataclass
class ModelArguments:
    """
    Arguments pertaining to which model/config/tokenizer we are going to fine-tune, or train from scratch.
    """
    model_name_or_path: Optional[str] = field(
        default = None,
        metadata = {
            "help": "The model checkpoint for weights initialization."
            "Don't set if you want to train a model from scratch."
        }
    )
    tokenizer_name_or_path: Optional[str] = field(
        default = None,
        metadata = {
            "help": "Pretrained tokenizer name or path if not the same as model_name"
        }
    )
    use_fast_tokenizer: bool = field(
        default = True,
        metadata = {
            "help": "Whether to use one of the fast tokenizer (backed by the tokenizers library) or not."
        }
    )
    do_lower_case: bool = field(
        default = True,
        metadata = {
            "help": "Whether to lower case the text during pretraining"
        }
    )

@dataclass
class DataTrainingArguments:
    """
    Arguments pertaining to what data we are going to input our model for training and eval.
    """
    train_dir: str = field(
        metadata={"help": "The input training data dir (dir that contain text files)."}
    )
    eval_dir: str = field(
        metadata={"help": "The input evaluation data dir (dir that contain text files)."},
    )
    binarized_path_train: Optional[str] = field(
        default=None,
        metadata={"help": "The path to the cached binrauzed train dataset."}
    )
    binarized_path_eval: Optional[str] = field(
        default=None,
        metadata={"help": "The path to the cached binrauzed eval dataset"},
    ) 
    checkpoint_dir: Optional[str] = field(
        default=None,
        metadata={"help": "The directory to the model checkpoint (for resume pretraining)."}
    )
    max_seq_length: Optional[int] = field(
        default=None,
        metadata={
            "help": "The maximum total input sequence length after tokenization. Sequences longer "
            "than this will be truncated."
        },
    )
    train_max_length: int = field(
         default=510,
    )
    eval_max_length: int = field(
         default=510,
    )
    mlm_probability: float = field(
        default=0.15, metadata={"help": "Ratio of tokens to mask for masked language modeling loss"}
    )
    pad_to_multiple_of: int = field(
        default=None,
        metadata={'help': 'Add padding tokens to the multiple of an integer specified (e.g. 8).'}
    )

    def __post_init__(self):
        if self.train_dir is None and self.eval_dir is None:
            raise ValueError("Need either a dataset name or a training/validation file.")


def is_main_process(rank):
    return rank in [-1, 0]


def main():

    parser = HfArgumentParser((ModelArguments, DataTrainingArguments, TrainingArguments,
                               ArchitectureArguments))

    (model_args, data_args, training_args, arch_args) = parser.parse_args_into_dataclasses()


    # Setup logging
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(name)s -   %(message)s",
        datefmt="%m/%d/%Y %H:%M:%S",
        level=logging.DEBUG if is_main_process(training_args.local_rank) else logging.WARN,
    )

     # Log on each process the small summary:
    logger.warning(
        f"Process rank: {training_args.local_rank}, device: {training_args.device}, n_gpu: {training_args.n_gpu}"
        + f"distributed training: {bool(training_args.local_rank != -1)}, 16-bits training: {training_args.fp16}"
    )

    # set seed
    set_seed(training_args.seed)

    tokenizer = AutoTokenizer.from_pretrained(model_args.tokenizer_name_or_path,
                                              use_fast=model_args.use_fast_tokenizer,
                                              do_lower_case=model_args.do_lower_case)
    tokenizer.additional_special_tokens = ['<s>NOTUSED', '</s>NOTUSED', '▁']
    logger.debug(f'\n\ntokenizer: {tokenizer}')

    config = AutoConfig.from_pretrained(arch_args.architecture)
    config.vocab_size = tokenizer.vocab_size
    
    logger.debug(f'\n\nconfig: {config}')


    if data_args.checkpoint_dir != None:
        logger.info(f'\n[INFO] Load pretrianed model (state_dict) from checkpoint: {data_args.checkpoint_dir}')
        model = AutoModelForMaskedLM.from_pretrained(data_args.checkpoint_dir)
    else:
        model = AutoModelForMaskedLM(config=config)

    # Load dataset
    train_dataset = MLMDataset(tokenizer, data_args.train_dir, data_args.train_max_length, binarized_path=data_args.binarized_path_train)
    eval_dataset = MLMDataset(tokenizer, data_args.eval_dir, data_args.eval_max_length, binarized_path=data_args.binarized_path_val)
    
    #data collator
    data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer,
                        mlm=True,
                        mlm_probability=data_args.mlm_probability,
                        pad_to_multiple_of=data_args.pad_to_multiple_of
                    )

    logger.debug(f'\n\ntraining_args: {training_args}')


    logging.info(" Number of devices: %d", training_args.n_gpu)
    logging.info(" Device: %s", training_args.device)
    logging.info(" Local rank: %s", training_args.local_rank)
    logging.info(" FP16 Training: %s", training_args.fp16)
    logging.info(" Run name: %s", training_args.run_name)
    logging.info(" deepspeed: %s", training_args.deepspeed)

    # Initiate Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        data_collator=data_collator,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
    )


    if data_args.checkpoint_dir != None:
        logger.info(f' \nTrainer resume from the checkpoint specified: {data_args.checkpoint_dir}.')
        trainer.train(resume_from_checkpoint=data_args.checkpoint_dir)
    else:
        trainer.train()

    if training_args.local_rank == 0:
            
        logger.info('\nSave tokenizer and model state')
        tokenizer.save_pretrained(os.path.join(training_args.output_dir, 'final_checkpoint-tokenizer'))
        trainer.save_model(os.path.join(training_args.output_dir, 'final_checkpoint-model'))

        logger.info('\n\nEvaluate final model checkpoint')
        eval_results = trainer.evaluate()
        if training_args.local_rank == 0:
            logger.info(f'\nEvaluation result: {eval_results}')

        return eval_results
