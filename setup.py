#!/usr/bin/env python3

from setuptools import setup

setup(
    name='run-ansible-pull',
    version='0.0.1',
    description='Runs Ansible Pull and reports to Sensu',
    author='Neil Hooey',
    author_email='nhooey@gmail.com',
    packages=['run_ansible_pull'],
    entry_points={
        'console_scripts': [
            'run-ansible-pull = run_ansible_pull.main:run',
        ],
    },
    install_requires=[
        'ConcurrentLogHandler',
        'psutil',
        'tendo == 0.2.15',
        'PyYAML',
    ],
)
