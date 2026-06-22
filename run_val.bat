@echo off
cd /d C:\Data_unsynced\git_repos\AIgen\skills
python run_design_validate.py > run_val_out.txt 2>&1
echo EXITCODE=%ERRORLEVEL% >> run_val_out.txt
