#!/usr/bin/env python3.8
# -*- coding: utf-8 -*-
"""
Logging
"""
import logging.config

def setup():
    """
        Initialization logging system
    """
    logging.config.fileConfig('/opt/app/logging.conf')
    logger = logging.getLogger("assistant")
    logger.propagate = False
    return logger