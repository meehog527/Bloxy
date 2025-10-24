@echo off
setlocal

:: Prompt for Raspberry Pi credentials
set /p PI_USER=Enter Raspberry Pi username: 
set /p PI_HOST=Enter Raspberry Pi hostname or IP: 
set /p PI_PASS=Enter Raspberry Pi password: 

:: Combine all setup commands into one SSH session
set CMD=sudo apt-get update 
&& sudo apt-get upgrade -y 
&& sudo apt-get install git --no-install-recommends -y 
&& sudo apt-get install pip
&& sudo apt install libcairo2-dev libgirepository1.0-dev python3-gi python3-gi-cairo gir1.2-gtk-3.0 install libdbus-1-dev libdbus-glib-1-dev python3-dbus
&& git clone https://github.com/meehog527/Bloxy.git 
&& cd Bloxy && python3 -m venv venv --system-site-packages && source venv/bin/activate && pip install -r requirements.txt

:: Run the command using plink
echo Running Bloxy setup on Raspberry Pi...
plink -ssh %PI_USER%@%PI_HOST% -pw %PI_PASS% "%CMD"

echo Setup complete.
pause
