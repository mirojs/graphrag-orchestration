#!/bin/bash
cd /afh/projects/graphrag-orchestration
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 graphrag-orchestration/test_invoice_verification.py
