##################################################################################
# This script is part of a package that works together to allow Raspberry Pi to control servos (for turnouts), LEDs (for signals)
# and Obstacle Avoidance sensors (to sense the end of the track)
# Start with this script and then read "RPi_TCPServer.py"
#
# This script assumes the Raspberry Pi is running a TCP server and controls turnouts, sensors and signal heads using its GPIO
# Script that controls GPIO change/status on networked devices using TCP/IP sockets
# The goal is to use cheap versatile computers as stationary decoders (independent of railway network - DCC, loconet, NCE, Lenz, ...).
# The turnouts assume that they are being controlled through Raspberry Pi I2C bus using PCM9685 servo control board
# The Signal Heads are controlled via Raspberry Pi I2C bus using MCP23017 GPIO control board
# The Obstacle Avoidance are controlled via Raspberry Pi's GPIO pins 
# 
# USAGE:
# This script is run on JMRI using (Panel Pro's Scripting --> Run Script), and it communicates with a Raspberry Pi via TCP sockets
#  OR, This script should be loaded at JMRI startup (preferred), and the script should run after JMRI has loaded the Tables with the appropriate System and User names for the turnouts, sensors and signal heads
#
#  This script runs on JPython interpretter that ships as part of JMRI. The accompanying code running on Raspberry Pi runs on CPython typically.
#
# This script sends commands to Raspberry Pi, which are shortend version of the command received from the various JMRI objects.
# This script taps into the JMRI Java listeners which allow us to modify the functionality of what happens when changes are made on JMRI 
# like operate a turnout, apply apperance change to signals etc.
# The commands sent to Raspberry Pi act as the translation from JMRI layout commands to raspberry pi connected sensors and actuators
#
# IMPORTANT:
# 1. This script acts as a TCP client, and will require the companion Raspberry Pi script which acts as the TCP server.
# 2. Networked devices will try to reconnect when connection is lost.
#
# JMRI Turnouts, Sensors and Signal Heads are configured in JMRI Panel Pro as "Internal" and have to follow specific pattern as shown below
#
# TURNOUT EXAMPLE:
# Internal Turnouts (system name):      [IT].RPI$<servoaddress>[thrown angle][closed angle]:<host>:<port>    (GPIO outputs: THROWN - set output to minimum angle / CLOSED - set output to max angle)
# Example: IT.RPI$0[85][95]:PI3BMODELTRAIN:142000 - This assumes that the servo being controlled is connected to the first servo control port of the PCM9685 board
# 
# SENSOR EXAMPLE: (JMRI should manage Sensor debouce delay)
# Internal Sensors (system name):       [IS].RPI$<gpio>:<host>:<port>    (GPIO inputs: INACTIVE - input is at +V / ACTIVE - input is connected to ground)
# Examples: IS.RPI$0:PI3BMODELTRAIN:14200
# 
# SIGNAL HEAD EXAMPLE:
# Internal SignalHead (user name):      [IH].RPI$<Signal Mast Num>-<Signal Head num>$<MCP23017 board I2C Add>$<Red LED GPIO>$<Green LED GPIO>:<Host>:<Port>
# Example: IH.RPI$SM1-SH1$0x24$R6$G14:PI3BMODELTRAIN:14200
# 
# Other examples:
# 
# 
#
# For testing purposes, there are two scripts available:
# - dummy_RPi.py - Pretends like a dummy Raspberry Pi and can be used to test the JMRI script running properly within JMRI
# - dummy_JMRI.py - Pretends like a JMRI and can be used to send commands to the Rasapberry Pi
#
#
# https://www.raspberrypi.org/
# https://gpiozero.readthedocs.io/
# https://www.gitbook.com/book/smartarduino/user-manual-for-esp-12e-devkit/details
# https://www.arduino.cc/
# http://www.codeproject.com/Articles/1073160/Programming-the-ESP-NodeMCU-with-the-Arduino-IDE
#
# WARNING:
# Devices GPIOs will be defined as INPUT or OUTPUT from a remote machine.
# Hardware protect (using resistors) each GPIO implemented as INPUT because a remote machine (JMRI) may set it as OUTPUT.
#
# To show debug messages, add the following line (without quotes) to the file 'default.lcf'
# located in the JMRI program directory: 'log4j.category.jmri.jmrit.jython.exec=DEBUG'
#
# Author: Oscar Moutinho (oscar.moutinho@gmail.com), 2016 - for JMRI
##################################################################################

#:::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
# imports, module variables and imediate running code

import java
import java.beans
import socket
import threading
import time
from org.apache.log4j import Logger
import jmri
import re

TcpPeripheral_log = Logger.getLogger("jmri.jmrit.jython.exec.TcpPeripheral")

CONN_TIMEOUT = 3.0 # timeout (seconds)
MAX_HEARTBEAT_FAIL = 5 # multiply by CONN_TIMEOUT for maximum time interval (send heartbeat after CONN_TIMEOUT * (MAX_HEARTBEAT_FAIL / 2))

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# get gpio and id from turnout or sensor system name
def TcpPeripheral_getSensorGpioId(sysName):
    gpio = None
    id = None
    _sysName = sysName.split(":")
    if len(_sysName) == 2 or len(_sysName) == 3:
        _gpio = _sysName[0].split("$")
        if len(_gpio) == 2:
            try:
                gpio = int(_gpio[1])
            except: # invalid GPIO
                gpio = 9999
            id = _sysName[1].strip() + ((":" + _sysName[2].strip()) if len(_sysName) > 2 else "")
    return gpio, id

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# get gpio and id from turnout or sensor system name
def TcpPeripheral_getTurnoutInfo(sysName):
    servoAdd = None
    id = None
    thrownAngle = None # The angle of the servo for THROWN position
    closedAngle = None # The angle of the sero for CLOSED position
    port = 10000
    TcpPeripheral_log.info("'TcpPeripheral' - decomposing turnout name: " + sysName)

    re_str = "([A-Za-z.]+\$([0-9]+)\[([0-9]+)\]\[([0-9]+)\]:([A-Z0-9.]+):*([0-9]*))" # sreach string to break down the turnout systemname
    grps = re.search (re_str, sysName)
    
    if(len(grps.groups()) == 6):
        servoAdd = int(grps.groups()[1])
        thrownAngle = int(grps.groups()[2])
        closedAngle = int(grps.groups()[3])
        id = grps.groups()[4]
        if (grps.groups()[5] is not None):
            port = grps.groups()[5]
            id = id + ":" + port

    return servoAdd, thrownAngle, closedAngle, id


#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# get Signal Head info string and host name for the signal control Raspberry Pi
def TcpPeripheral_getSignalHeadInfo(sysName):
    signalHeadCmdStr = ""
    host = None
    port = 10000

    # Pattern to parse IH.RPI$SM1-SH1$0x24$R6$G14:PI3BMODELTRAIN:14200
    re_str = "(IH.RPI\$([A-Z0-9\-\$x]+):([A-Z0-9\.]+):?([0-9]*))" # sreach string to break down the turnout systemname
    grps = re.search (re_str, sysName)
    
    if(len(grps.groups()) == 4):
        signalHeadCmdStr = (grps.groups()[1])
        host = grps.groups()[2]
        if (grps.groups()[3] is not None):
            port = grps.groups()[3]
            host = host + ":" + port

    print ("Cmd Str: " + signalHeadCmdStr)
    print ("host: " + host)

    return signalHeadCmdStr, host

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# this is the code to be executed for a new network device
def TcpPeripheral_addDevice(id):
    alias = id.lower()
    _aux = id.split(":")
    host = _aux[0]
    try:
        port = int(_aux[1])
    except: # invalid port
        port = 10000 # default
    if alias not in TcpPeripheral_sockets:
        TcpPeripheral_sockets[alias] = TcpPeripheral_clientTcpThread(alias, TcpPeripheral_clientTcpThread_callback(), host, port)
        TcpPeripheral_sockets[alias].start()
    count = MAX_HEARTBEAT_FAIL # loop n times max (use this constant for convenience)
    while (not TcpPeripheral_sockets[alias].isAtive) and (count > 0): # try to wait for slow connection
        count -= 1
        time.sleep(CONN_TIMEOUT)
    return

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# this is the code to be executed to close and remove a network device
def TcpPeripheral_removeDevice(id):
    alias = id.lower()
    if alias in TcpPeripheral_sockets:
        TcpPeripheral_sockets[alias].stop()
        del TcpPeripheral_sockets[alias]
    return

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# this is the code to be executed to send a message to a network device connected to the sensor
def TcpPeripheral_sendToSensor(gpio, id):
    alias = id.lower()
    msg = "IN:" + str(gpio)
    sent = TcpPeripheral_sockets[alias].send(msg)
    return sent

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# this is the code to be executed to send a message to a network device connected to the turnout
def TcpPeripheral_sendToTurnout(sensorAdd, thrownAngle, closedAngle, id, active):
    alias = id.lower()
    msg = "OUT_TO:" + str(sensorAdd) + "[" + str(thrownAngle) + "][" + str(closedAngle) +  "]:" + ("1" if active else "0")
    sent = TcpPeripheral_sockets[alias].send(msg)
    return sent

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# this is the code to be executed to send a message to a network device connected to the signal head
def TcpPeripheral_sendToSignalHead(signalHeadCmdStr, host, apperance):
    alias = host.lower()
    msg = "OUT_SH:" + signalHeadCmdStr + ":" + apperance
    sent = TcpPeripheral_sockets[alias].send(msg)
    return sent

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# this is the code to be executed when a valid sensor status is received from a network device
def TcpPeripheral_receivedFromDevice(alias, gpio, value):
    sensorSysName = "IS.RPI$" + str(gpio) + ":" + alias.upper()
    sensor = sensors.getBySystemName(sensorSysName)
    if sensor != None: # sensor exists
        if value:
            sensor.setKnownState(jmri.Sensor.ACTIVE)
        else:
            sensor.setKnownState(jmri.Sensor.INACTIVE)
    else: # sensor does not exist
        TcpPeripheral_log.error("'TcpPeripheral' - " + alias + ": Feedback for non-existent Sensor [" + sensorSysName + "]")
    return

#=================================================================================
# define the TCP client callback class
class TcpPeripheral_clientTcpThread_callback(object):

#---------------------------------------------------------------------------------
# this is the code to be executed when a message is received
    def processRecvMsg(self, clientTcpThread, msg):
        TcpPeripheral_log.debug("'TcpPeripheral' - " + clientTcpThread.alias + ": Received [" + msg + "]")
        _msg = msg.split(":")
        alias = clientTcpThread.alias
        if len(_msg) == 3 and _msg[0].upper() == "IN":
            try:
                gpio = int(_msg[1])
            except: # invalid GPIO
                gpio = 9999
            if _msg[2] == "1":
                TcpPeripheral_receivedFromDevice(alias, gpio, True)
            if _msg[2] == "0":
                TcpPeripheral_receivedFromDevice(alias, gpio, False)
        else: # invalid feedback
            TcpPeripheral_log.error("'TcpPeripheral' - " + alias + ": Invalid feedback [" + msg + "]")
        return

#---------------------------------------------------------------------------------
# this is the code to be executed on stop
    def onFinished(self, clientTcpThread, msg):
        TcpPeripheral_log.info("'TcpPeripheral' - " + clientTcpThread.alias + ": " + msg)
        return

#=================================================================================
# define the TCP client thread class
class TcpPeripheral_clientTcpThread(threading.Thread):

#---------------------------------------------------------------------------------
# this is the code to be executed when the class is instantiated
    def __init__(self, alias, callback, ip, port):
        threading.Thread.__init__(self)
        self.alias = alias
        self.callback = callback
        self.ip = ip
        self.port = port
        self.received = ""
        self.isAtive = False
        self.exit = False
        self.sock = None
        return

#---------------------------------------------------------------------------------
# this is the code to be executed on start
    def run(self):
        self.connect() # connect
        heartbeatFailCount = 0
        heartbeatCtrl = time.time() # start heartbeat delay
        while not self.exit:
            if (time.time() - heartbeatCtrl) > (CONN_TIMEOUT * (MAX_HEARTBEAT_FAIL / 2)): # send only after appropriate delay
                self.sock.sendall(" ") # send heartbeat
                heartbeatCtrl = time.time() # restart heartbeat delay
            try:
                received = self.sock.recv(256)
                if received:
                    TcpPeripheral_log.debug("'TcpPeripheral' - " + self.alias + ": Received (including heartbeat) [" + received + "]")
                    heartbeatFailCount = 0
                    self.received += received.replace(" ", "") # remove spaces (heartbeat)
                    cmds = self.received.split("|")
                    if len(cmds) > 0:
                        for cmd in cmds:
                            if cmd: # if not empty
                                self.callback.processRecvMsg(self, cmd)
                        procChars = self.received.rfind("|")
                        self.received = self.received[procChars:]
                else:
                    TcpPeripheral_log.error("'TcpPeripheral' - " + self.alias + ": Connection broken - closing socket")
                    self.sock.close()
                    self.isAtive = False
                    self.connect() # reconnect
                    heartbeatFailCount = 0
            except socket.timeout as e:
                heartbeatFailCount += 1
                if heartbeatFailCount > MAX_HEARTBEAT_FAIL:
                    TcpPeripheral_log.error("'TcpPeripheral' - " + self.alias + ": Heartbeat timeout - closing socket")
                    self.sock.close()
                    self.isAtive = False
                    self.connect() # reconnect
                    heartbeatFailCount = 0
            except:
                TcpPeripheral_log.error("'TcpPeripheral' - " + self.alias + ": Connection reset by peer - closing socket")
                self.sock.close()
                self.isAtive = False
                self.connect() # reconnect
                heartbeatFailCount = 0
        self.callback.onFinished(self, "Finished")
        return

#---------------------------------------------------------------------------------
# this is the code to be executed to connect or reconnect
    def connect(self):
        server_address = (self.ip, self.port)
        while not self.exit:
            TcpPeripheral_log.info("'TcpPeripheral' - " + self.alias + ": Connecting socket thread to '%s' port %s" % server_address)
            try:
                self.sock = socket.create_connection(server_address, CONN_TIMEOUT)
            except socket.error as e:
                TcpPeripheral_log.error("'TcpPeripheral' - " + self.alias + ": ERROR - " + str(e))
                self.sock = None
                time.sleep(CONN_TIMEOUT)
            else:
                TcpPeripheral_log.info("'TcpPeripheral' - " + self.alias + ": Connected to '%s' port %s" % server_address)
                self.isAtive = True
                break # continue because connection is done
        return

#---------------------------------------------------------------------------------
# this is the code to be executed to send a message
    def send(self, msg):
        if self.isAtive:
            TcpPeripheral_log.debug("'TcpPeripheral' - '" + self.alias + "' sending message: " + msg)
            try:
                self.sock.sendall(msg + "|") # add end of command delimiter
            except:
                TcpPeripheral_log.error("'TcpPeripheral' - " + self.alias + ": Error sending - closing socket")
                self.sock.close()
                self.isAtive = False
                self.connect() # reconnect
                heartbeatFailCount = 0
        else:
            TcpPeripheral_log.error("'TcpPeripheral' - '" + self.alias + "' message [" + msg + "] not sent")
        return self.isAtive

#---------------------------------------------------------------------------------
# this is the code to be executed to close the socket and exit
    def stop(self):
        TcpPeripheral_log.info("'TcpPeripheral' - " + self.alias + ": Stop the socket thread - closing socket")
        try:
            self.sock.close()
        except: # ignore possible error if connection not ok
            pass
        finally:
            self.isAtive = False
            self.exit = True
        return

#=================================================================================
# define the listener class for Sensors
class TcpPeripheral_Sensor_Listener(java.beans.PropertyChangeListener):

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def propertyChange(self, event):
        sensor = event.getSource()
        sensorName = sensor.getDisplayName(jmri.NamedBean.DisplayOptions.USERNAME_SYSTEMNAME)
        TcpPeripheral_log.debug("'TcpPeripheral' - Sensor=" + sensorName + " property=" + event.propertyName + "]: oldValue=" + str(event.oldValue) + " newValue=" + str(event.newValue))
        if event.propertyName == "KnownState": # only this property matters
            gpio, id = TcpPeripheral_getSensorGpioId(sensor.getSystemName())
            sent = TcpPeripheral_sendToSensor(gpio, id)
            if not sent: # set as unknown
                sensor.setKnownState(jmri.Sensor.UNKNOWN)
        return

#=================================================================================
# define the listener class for Turnouts
class TcpPeripheral_Turnout_Listener(java.beans.PropertyChangeListener):

#---------------------------------------------------------------------------------
# this is the code to be executed when the class is instantiated
    def __init__(self):
        self.turnoutCtrl = None # for turnout restore control
        return

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def propertyChange(self, event):
        turnout = event.getSource()
        turnoutName = turnout.getDisplayName(jmri.NamedBean.DisplayOptions.USERNAME_SYSTEMNAME)
        TcpPeripheral_log.debug("'TcpPeripheral' - Turnout=" + turnoutName + " property=" + event.propertyName + "]: oldValue=" + str(event.oldValue) + " newValue=" + str(event.newValue) + " turnoutCtrl=" + str(self.turnoutCtrl))
        if event.propertyName == "CommandedState": # only this property matters
            if event.newValue != self.turnoutCtrl: # this is a state change request
                sensorAdd, thrownAngle, closedAngle, id = TcpPeripheral_getTurnoutInfo(turnout.getSystemName())
                sent = True
                if event.newValue == jmri.Turnout.CLOSED:
                    sent = TcpPeripheral_sendToTurnout(sensorAdd, thrownAngle, closedAngle, id, True)
                if event.newValue == jmri.Turnout.THROWN:
                    sent = TcpPeripheral_sendToTurnout(sensorAdd, thrownAngle, closedAngle, id, False)
                if sent: # store the current state
                    self.turnoutCtrl = event.newValue
                else: # restore turnout state
                    self.turnoutCtrl = event.oldValue
                    turnout.setCommandedState(event.oldValue)
        return

#=================================================================================
# define the shutdown task class
class TcpPeripheral_ShutDown(jmri.implementation.AbstractShutDownTask):

#---------------------------------------------------------------------------------
# this is the code to be invoked when the program is shutting down
    def run(self):
        auxList = []
        for alias in TcpPeripheral_sockets:
            auxList.append(alias)
        for alias in auxList:
            TcpPeripheral_removeDevice(alias)
        TcpPeripheral_log.info("Shutting down 'TcpPeripheral'.")
        time.sleep(3) # wait 3 seconds for all sockets to close
        return

#================================================================================
# Listener for Signal Heads

class TcpPeripheral_SignalHead_Listener (java.beans.PropertyChangeListener):
    def propertyChange(self, event):
        if (event.propertyName == "Appearance"):
            oldState = event.source.getAppearanceName(event.oldValue)
            newState = event.source.getAppearanceName(event.newValue)
            TcpPeripheral_log.debug("'TcpPeripheral' - SignalHead [" + event.source.userName + "] Apperance has changed from " + oldState + " to " + newState )

            signalHeadCmdStr, host = TcpPeripheral_getSignalHeadInfo(event.source.userName)

            if newState == "Green":
                TcpPeripheral_sendToSignalHead(signalHeadCmdStr, host, "g") # Green
            elif newState == "Red":
                TcpPeripheral_sendToSignalHead(signalHeadCmdStr, host, "r") # Red
            elif newState == "Flashing Red":
                TcpPeripheral_sendToSignalHead(signalHeadCmdStr, host, "fr") # Flashing red
            elif newState == "Flashing Green":
                TcpPeripheral_sendToSignalHead(signalHeadCmdStr, host, "fg") # Flashing grenn
            else:
                TcpPeripheral_sendToSignalHead(signalHeadCmdStr, host, "d") # Dark
        return


#*********************************************************************************

if globals().get("TcpPeripheral_running") != None: # Script already loaded so exit script
    TcpPeripheral_log.warn("'TcpPeripheral' already loaded and running. Restart JMRI before load this script.")
else: # Continue running script
    TcpPeripheral_log.info("'TcpPeripheral' started.")
    TcpPeripheral_running = True
    TcpPeripheral_sockets = {}
    shutdown.register(TcpPeripheral_ShutDown("TcpPeripheral"))

    #Iterate through all the sensors and add listners to the sensors so when something changes on the model layout, JMRI can be informed
    for sensor in sensors.getNamedBeanSet():
        # Parse the info from the system name of the sensor
        gpio, id = TcpPeripheral_getSensorGpioId(sensor.getSystemName())
        TcpPeripheral_log.debug("'TcpPeripheral' - Sensor SystemName [" + sensor.getSystemName() + "] GPIO [" + str(gpio) + "] ID [" + str(id) + "]")
        if gpio != None and id != None:
            # Add the host server to a list of connections
            TcpPeripheral_addDevice(id)
            sensor.setKnownState(jmri.Sensor.INCONSISTENT) # set sensor to inconsistent state (just to detect change to unknown)
            sensor.addPropertyChangeListener(TcpPeripheral_Sensor_Listener()) # Setup listener for the sensor change handling
            sensor.setKnownState(jmri.Turnout.UNKNOWN) # to force send a register request to device

    # Iterate through all the turnouts and add listners to the turnouts so when something changes on the JMRI layout, command can be sent to RPi
    for turnout in turnouts.getNamedBeanSet():
       
        # Skip over all the turnouts that are part of the virtual turnouts setup with the signal heads
        if "Virtual" not in turnout.getSystemName():
             # Parse the info from the system name of the sensor
            servoAdd, thrownAngle, closedAngle, id = TcpPeripheral_getTurnoutInfo(turnout.getSystemName())
            
            TcpPeripheral_log.debug("'TcpPeripheral' - Turnout SystemName [" + turnout.getSystemName() + "] Servo [" + str(servoAdd) + "] ID [" + str(id) + "] Kown State [" + str(turnout.getKnownState()) + "]")
            if servoAdd != None and id != None: # should be a valid network device and GPIO
                # Add the host server to a list of connections
                TcpPeripheral_addDevice(id)
                currentState = turnout.getCommandedState() # get current turnout state
                turnout.setCommandedState(jmri.Turnout.UNKNOWN) # set turnout to a state that will permit change detection by listener
                # Set the listener for the turnout change communicated from JMRI
                turnout.addPropertyChangeListener(TcpPeripheral_Turnout_Listener())
                # Apply the changes so it triggers the ncessary changes
                if currentState == jmri.Turnout.CLOSED:
                    turnout.setCommandedState(jmri.Turnout.CLOSED)
                if currentState == jmri.Turnout.THROWN:
                    turnout.setCommandedState(jmri.Turnout.THROWN)

    # Iterate through the signal heads and add listners so when something changes on the JMRI layout, command can be sent to RPi
    for signalhead in signals.getNamedBeanSet():
        # Parse signalhead name to identify the host name and signal command string
        signalHeadCmdStr, host = TcpPeripheral_getSignalHeadInfo(signalhead.getUserName()) 
        TcpPeripheral_log.info(" 'TcpPeripheral' - Processing SignalHead " + signalhead.getUserName())

        if (host != None):
            # Add host if not already present
            TcpPeripheral_addDevice(host)
            TcpPeripheral_log.info("'TcpPeripheral' - SignalHead [" + signalhead.getUserName() + "] @ Host: [" + host + "]")
            # Get the current state of the signal head before initializing the listener
            #currSignalHeadState = signalhead.getAppearance()
            # Set the state to "yellow" so we can reinitialize the signal
            #signalhead.setAppearance(4)  # 4 is the Enum for Yellow
            # Add listener to the Signal Head
            signalhead.addPropertyChangeListener(TcpPeripheral_SignalHead_Listener())
            #Once listeners are added, reset the state so message is sent to the layout
            #if signalhead.getAppearanceName(currSignalHeadState) == "Dark":
            #    signalhead.setApperance(0) # 0 is the Enum for Dark
            #if signalhead.getAppearanceName(currSignalHeadState) == "Red":
            #    signalhead.setApperance(1) # 1 is the Enum for Red
            #if signalhead.getAppearanceName(currSignalHeadState) == "Flashing Red":
            #    signalhead.setApperance(2) # 2 is the Enum for Flashing Red
            #if signalhead.getAppearanceName(currSignalHeadState) == "Green":
            #    signalhead.setApperance(16) # 16 is the Enum for Green
            #if signalhead.getAppearanceName(currSignalHeadState) == "Flashing Green":
            #    signalhead.setApperance(32) # 32 is the Enum for Flashing Green
            
