##################################################################################

The goal of this project is to control networked devices in a standard way using JMRI.

Each device may be seen as a stationary decoder but instead of using DCC, LOCONET, NCE or any other railroad connection/protocol,
they communicate with JMRI computer using WiFi on the local area network (LAN).

----------------------------------------------------------------------------------

JMRI will control servo outputs (assuing there is a motor driver using PCM9685) using Turnouts defined as internal:
System name:	[IT].RPi$<servoaddress>[<thrown angle>][<closed angle>]:<deviceId>	
	Examples:
IT.RPi$0[80][100]:192.168.200.1 - set servo 0 with 'thrown' angle 80 and 'closed' angle 100 with IP address 192.168.200 listening at port 10000 (default port)

JMRI will receive feedback from pin inputs using Sensors defined as internal:
System name:	[IS].RPi$<pin>:<deviceId>	(pin inputs: INACTIVE - input is at +V / ACTIVE - input is connected to ground)
	Examples:
IS.RPi$8:192.168.200 - GPIO pin 8 as input on device with IP address 192.168.200 listening at port 10000 (default port)
IS.RPi$13:dev1.mylayout.com - GPIO pin 13 as input on device with server name 'dev1.mylayout.com' listening at port 10000 (default port)
IS.RPi$5:192.168.201:12345 - GPIO pin 5 as input on device with IP address 192.168.201 listening at port 12345

----------------------------------------------------------------------------------

  PLEASE READ THE INFORMATION AT THE BEGINNING OF EACH SCRIPT FILE

- dummy_RPi.py
- dummy_JMRI.py
- JMRI_script.py
- RPi_TCPServer.py

This is important to get the most of this solution.

----------------------------------------------------------------------------------

For testing purposes, you may use the following scripts:

dummy_RPi.py - runs on python 2.7 (no JMRI needed) to simulate a networked device (stationary decoder)
dummy_JMRI.py - runs on python 2.7 (no JMRI needed) to simulate JMRI running JMRI_TcpPeripheral.py (the JMRI computer)

This is the script to load at JMRI startup:
JMRI_script.py

This is the script to run at startup on Raspberry Pis:
RPi_TCPServer.py


For aditional information look at the following links and search for related info:
(it is important to have some electronic knowledge to get the most of GPIO interfaces - LEDs, buttons, relays, reed switches, ...)
https://www.raspberrypi.org/
https://gpiozero.readthedocs.io/
https://www.gitbook.com/book/smartarduino/user-manual-for-esp-12e-devkit/details
https://www.arduino.cc/
http://www.codeproject.com/Articles/1073160/Programming-the-ESP-NodeMCU-with-the-Arduino-IDE

Using the implemented protocol anyone may develop script variations for these and other devices.

----------------------------------------------------------------------------------

Networked devices will try to reconnect when connection is lost.
Technically, the devices communicate using TCP sockets over IP.
There are no technical limitations to extend the control of these devices using physical network cables and over the internet.
(but I think cables are not welcome and internet security is an issue)
These networked devices may not only interact with the railroad but they may also control sound, room light, ... anything you want.
This is RPi 

----------------------------------------------------------------------------------

Author: Oscar Moutinho (oscar.moutinho@gmail.com), 2016 - for JMRI
##################################################################################
