#!/bin/bash
cd /c/Data_unsynced/git_repos/AIgen/skills
python run_check.py > /c/Data_unsynced/git_repos/AIgen/skills/check_out.txt 2>&1
echo "EXIT:$?" >> /c/Data_unsynced/git_repos/AIgen/skills/check_out.txt
