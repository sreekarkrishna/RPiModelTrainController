##################################################################################
# Please read JMRI_Script.py first to understand the nature of this code base
#
# This code is part of the package for controlling sensors and actuators that are connected to a Raspberry Pi to work with JMRI
# Goal is to create cheap sensor/actuator network controlled by Raspberry Pi
# This code is typically run through the CPython interpretter on the Pi
# 
# This code does a few things:
# 1. Using Socket library, creates a TCP server on the Raspberry Pi which listens for connections from JMRI
# 2. Uses Raspberry Pi's GPIOs for sensor input from Obstacle avoidance sensors
# 3. Uses Raspberry Pi's I2C bus to control PCM9685 servo controller board to act as Turnout actuators
# 4. Uses Raspberry Pi's I2C bus to control MCP23017 GPIO Extender baord to control LED Signal Lights
# 5. Acts as broker between JMRI and Raspberry Pi to interpret a set of commands that controls back and forth comms between JMRI and Raspberry Pi
# 6. This script will try to reconnect when connection is lost.
#
# Usage: python<3> <thisScript>.py [<port>(14200)]
#
# Here are examples of the communications between Raspberry Pi and JMRI:
# Receive (Change Tunrout Position):         OUT_TO:<Servo Address>[<Thrown Angle>][<Closed Angle>]:<0 or 1> 0 for Closed and 1 for Thrown
# Receive (Change Signal Head Appearance):         OUT_SH:<Sig Head ID>$<MCP Board I2C Address>$R<Red LED GPIO>$G<Green LED GPIO>:<r/g/d/fr/fg>
# Send (input GPIO):                    IN:<gpio>:0, IN:<gpio>:1        (0 - input is at +V / 1 - input is connected to ground)
# Send (errors):                        ERROR 
#
# Note: 
#      1. For Turnouts the valid states are CLOSED and THROWN
#      2. For Sensors, the states are ACTIVE and INACTIVE
#      3. For Signal Heads, the states are RED (r), Green (g), Flasing Red (fr), Flashing Green (fg), Dark (d)
#   
# WARNING:
# GPIO will be defined as INPUT or OUTPUT from a remote machine.
# Hardware protect (using resistors) each GPIO implemented as INPUT because a remote machine may set it as OUTPUT.
#
# Each command/status sent or received must end with a '|' (pipe).
# A string received without a '|' (pipe) is not managed as a command/status until a '|' (pipe) is received in a new message.
# A trailing '|' (pipe) is automatically appended when sending a message.
# Spaces are ignored (they are used as heartbeat control).
# 
# Libraries used:
# The two important libraraies are the GPIOZero for Raspberry Pi and Circuit Python from Adafruit
# http://gpiozero.readthedocs.io - General IO Operations
# https://circuitpython.readthedocs.io/projects/servokit/en/latest/ - adafruit_servokit - Library for controlling PCM9685 
# https://circuitpython.readthedocs.io/projects/mcp230xx/en/latest/api.html - adafruit_mcp230xx.mcp23017 - Library for controlling MCP23017
# 
# Author: Oscar Moutinho (oscar.moutinho@gmail.com), 2016 - for JMRI
##################################################################################

#:::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
# imports, module variables and imediate running code

import gpiozero
import socket
import threading
import time
import sys
import re
from adafruit_servokit import ServoKit
import board
import busio
from digitalio import Direction
from adafruit_mcp230xx.mcp23017 import MCP23017


FLASHING_FREQ = 2
CONN_TIMEOUT = 3.0 # timeout (seconds)
MAX_HEARTBEAT_FAIL = 5 # multiply by CONN_TIMEOUT for maximum time interval (send heartbeat after CONN_TIMEOUT * (MAX_HEARTBEAT_FAIL / 2))

# Hashmaps to keep track of various continuously running things
gpioOUT = {}
gpioIN = {}
serverTURNOUT = {}
serverSignalHead = {}
blinkingthreadCtrlFlag = {}
blinkingThreads = {}


#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# this is the code to be executed when an input is activated
def inputActivated(input):
    msg = "IN:" + str(input.pin.number) + ":1"
    sock.send(msg)
    return

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# this is the code to be executed when an input is deactivated
def inputDeactivated(input):
    msg = "IN:" + str(input.pin.number) + ":0"
    sock.send(msg)
    return

#=================================================================================
# define the TCP server callback class
class serverTcpThread_callback(object):

    # A mrethod for blinking red and green LEDs
    def _flashing_LED(self, pin, sigHeadID, stop):
        dutyCycle = 0.5
        onSecs = (1.0 / FLASHING_FREQ) * dutyCycle
        offSecs = (1.0 / FLASHING_FREQ) * (1 - dutyCycle)

        while(True):
            try:
                pin.value = True
                time.sleep(onSecs)
                pin.value = False
                time.sleep(offSecs)
                if (stop()):
                    #print (f"Closing thread for {sigHeadID}")
                    break
            except Exception as err:
                msg = " Exception ERROR " + str(err) + " in blinking led thread for signal head " + sigHeadID
                serverTcpThread.send(msg)
                raise
            

#---------------------------------------------------------------------------------
# this is the code to be executed when a message is received
    def processRecvMsg(self, serverTcpThread, msg):
        #print ("From '" + serverTcpThread.client + "': Received [" + msg + "]")
        tempMsg = msg # for temp storage
        cmdParams = msg.split(":")
        if len(cmdParams) < 2 or (cmdParams[0].startswith("OUT") and cmdParams[0].startswith("IN")): # generic error
            msg = "ERROR parsing commpand sent from JMRI " + tempMsg
            serverTcpThread.send(msg)
            return

        inout = cmdParams[0].upper()



        # Handle the turnout commands
        if inout == "OUT_TO":
            servoAdd = None
            thrownAngle = None # The angle of the servo for THROWN position
            closedAngle = None # The angle of the sero for CLOSED position
            active = None

            if len(cmdParams) != 3: # error for OUT command
                msg = inout + ":" + str(tempMsg) + ":ERROR - Not enough parameters for servo control"
                serverTcpThread.send(msg)
                return
            
            re_str = "OUT_TO:([0-9]+)\[([0-9]+)\]\[([0-9]+)\]:([0-1]+)" # sreach string to break down the turnout systemname
            grps = re.search (re_str, tempMsg)

            try:
                servoAdd = int(grps.groups()[0])
                thrownAngle = int(grps.groups()[1])
                closedAngle = int(grps.groups()[2]) 
                active = (True if int(grps.groups()[3]) == 1 else False)
            except:
                msg = inout + ":" + str(tempMsg) + ":ERROR - could not parse parameters for servo control"
                serverTcpThread.send(msg)
                return

            if servoAdd not in serverTURNOUT:
                try:
                    servoCtrlKit = ServoKit(channels=16)
                except:
                    msg = inout + ":" + str(tempMsg) + ":ERROR - could not initiate servo controller"
                    serverTcpThread.send(msg)
                    return     
                else:
                    serverTURNOUT[servoAdd] = servoCtrlKit

            if active:
                serverTURNOUT[servoAdd].servo[servoAdd].angle = closedAngle
                #print ("Servo " + str(servoAdd) + " set to CLOSED")
            else:
                serverTURNOUT[servoAdd].servo[servoAdd].angle = thrownAngle
                #print ("Servo " + str(servoAdd) + " set to THROWN")




        # Handle the command for Signalheads
        if inout == "OUT_SH":
            signalHeadId = None
            MCPBoardAdd = None
            redLEDGPIO = None
            greenLEDGPIO = None

            # Sample incoming command OUT_SH:SM1-SH1$0x24$R6$G14:r
            re_str = "(OUT_SH:([A-Z0-9\-]+)\$([0-9x]+)\$R([0-9]+)\$G([0-9]+):([r,g,f,d]+))" # sreach string to break down the turnout systemname
            
            try:
                grps = re.search (re_str, tempMsg)

                if grps == None or len(grps.groups()) != 6:
                    msg = str(tempMsg) + ":ERROR - regex returned None, or inconsistent groups"
                    serverTcpThread.send(msg)
                    return     

                signalHeadId = grps.groups()[1]
                MCPBoardAdd = int(grps.groups()[2], 16)
                redLEDGPIO = int(grps.groups()[3])
                greenLEDGPIO = int(grps.groups()[4])
                apperance = grps.groups()[5]

                msg = "Extracted from Regex - MCPBoardAdd: " + str(MCPBoardAdd) + " red gpio: " + str(redLEDGPIO) + " green gpio: " + str(greenLEDGPIO) + " apperance: " + apperance
                serverTcpThread.send(msg)
            except:
                msg = str(tempMsg) + ":ERROR - could not parse due to exception in parsing parameters for Signal Head " + signalHeadId
                serverTcpThread.send(msg)
                return

            # If the MCP board at the right address is not initialized, do it
            if MCPBoardAdd not in serverSignalHead:
                try:
                    i2c = busio.I2C(board.SCL, board.SDA)
                    mcpboard = MCP23017(i2c, address=MCPBoardAdd)
                    serverSignalHead[MCPBoardAdd] = mcpboard
                    # Initialize all the pins to output
                    for i in range(0,16):
                        pin = mcpboard.get_pin(i)
                        pin.direction = Direction.OUTPUT
                        pin.value = False
                except:
                    msg = str(tempMsg) + ":ERROR - could not initialize board for Signal Head " + signalHeadId
                    serverTcpThread.send(msg)
                    return

            # Before setting the Signal Head to appropriate appearance, see if any of the LEDs in this SignalHead are blinking
            # If they are blinking, kill the thread so we can reset to new appearace
            try:
                if signalHeadId in blinkingthreadCtrlFlag.keys():
                    trd = blinkingThreads[signalHeadId]
                    blinkingthreadCtrlFlag[signalHeadId] = True # This will enact the stop() condition within the thread's while loop
                    trd.join() # This is needed to bring the thread back into the main and kill it
                    blinkingThreads.pop(signalHeadId) # Poping the item from the dictionary so we can make sure the same LED doesnt get into an orphan state
                    blinkingthreadCtrlFlag.pop(signalHeadId)
            except:
                msg = str(tempMsg) + " : ERROR - could not close the thread for blinking LED " + signalHeadId
                serverTcpThread.send(msg)
                return
                

            # Send the command to the GPIO
            try:
                redPin = serverSignalHead[MCPBoardAdd].get_pin(redLEDGPIO)
                greenPin = serverSignalHead[MCPBoardAdd].get_pin(greenLEDGPIO)
                if apperance == "r":
                    redPin.value = True
                    greenPin.value = False
                elif apperance == "g":
                    redPin.value = False
                    greenPin.value = True
                elif apperance == "fr":
                    # For flashing red make sure green is off
                    greenPin.value = False
                    # Initiate a thread aht will start flashing the red LED
                    blinkingthreadCtrlFlag[signalHeadId] = False # This will make sure the stopping condition in the LED blinking thread is kept false
                    trd = threading.Thread(target=self._flashing_LED, args=[redPin, signalHeadId, lambda : blinkingthreadCtrlFlag[signalHeadId]]) # The lambda converts the dictionary flag into a fucntion that will be called by the thread
                    trd.start()
                    blinkingThreads[signalHeadId] = trd
                elif apperance == "fg":
                    # For flashing green make sure red is off
                    redPin.value = False
                    # Initiate a thread aht will start flashing the green LED
                    blinkingthreadCtrlFlag[signalHeadId] = False # This will make sure the stopping condition in the LED blinking thread is kept false
                    trd = threading.Thread(target=self._flashing_LED, args=[greenPin, signalHeadId, lambda : blinkingthreadCtrlFlag[signalHeadId]]) # The lambda converts the dictionary flag into a fucntion that will be called by the thread
                    trd.start()
                    blinkingThreads[signalHeadId] = trd
                else:
                    redPin.value = False
                    greenPin.value = False
            except Exception as err:
                msg = str(tempMsg) + ":ERROR " + str(err) + " - could not set the LED GPIOs board for Signal Head " + signalHeadId 
                serverTcpThread.send(msg)
                return
                    

            
            

        # Setup the different sensors for triggering 
        if inout == "IN":
            try:
                pin = int(cmdParams[1])
            except: # invalid GPIO
                pin = 9999
                msg = inout + ":" + str(pin) + ":ERROR"
                serverTcpThread.send(msg)
                return
            if len(cmdParams) != 2: # error for IN command
                msg = inout + ":" + str(pin) + ":ERROR"
                serverTcpThread.send(msg)
                return
            if pin not in gpioIN: # try to configure GPIO as input and add it to the list
                if pin in gpioOUT: # already defined for output
                    gpioOUT[pin].close() # close it and free resources
                    del gpioOUT[pin] # remove it
                try:
                    gpioAux = gpiozero.Button(pin, True) # pullup resistor
                except:
                    msg = inout + ":" + str(pin) + ":ERROR"
                    serverTcpThread.send(msg.encode())
                    return
                else:
                    gpioIN[pin] = gpioAux
                    gpioIN[pin].when_pressed = inputActivated
                    gpioIN[pin].when_released = inputDeactivated
            #print ("GPIO " + str(pin) + " registered for input")
            if gpioIN[pin].is_pressed:
                inputActivated(gpioIN[pin])
            else:
                inputDeactivated(gpioIN[pin])
        return

#---------------------------------------------------------------------------------
# this is the code to be executed on stop
    def onFinished(self, serverTcpThread, msg):
        #print ("Connection to '" + serverTcpThread.client + "': " + msg)
        pass
        return

#=================================================================================
# define the TCP server thread class
class serverTcpThread(threading.Thread):

#---------------------------------------------------------------------------------
# this is the code to be executed when the class is instantiated
    def __init__(self, callback, port):
        threading.Thread.__init__(self)
        self.callback = callback
        self.port = port
        self.client = ""
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
                msg = " "
                self.sock.sendall(msg.encode()) # send heartbeat
                heartbeatCtrl = time.time() # restart heartbeat delay

            try:
                received = self.sock.recv(256)
                received = received.decode()
                if received:
                    #print ("'" + self.client + "': Received (including heartbeat) [" + received + "]")
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
                    #print ("'" + self.client + "': Connection broken - closing socket")
                    self.sock.close()
                    self.isAtive = False
                    self.connect() # reconnect
                    heartbeatFailCount = 0
            except socket.timeout as e:
                heartbeatFailCount += 1
                if heartbeatFailCount > MAX_HEARTBEAT_FAIL:
                    #print ("'" + self.client + "': Heartbeat timeout - closing socket")
                    self.sock.close()
                    self.isAtive = False
                    self.connect() # reconnect
                    heartbeatFailCount = 0
            except socket.error as e:
                #print ("'" + self.client + "': " + e + " - Connection reset by peer - closing socket")
                self.sock.close()
                self.isAtive = False
                self.connect() # reconnect
                heartbeatFailCount = 0
        self.callback.onFinished(self, "Finished")
        return

#---------------------------------------------------------------------------------
# this is the code to be executed to connect or reconnect
    def connect(self):
        server_address = ("", self.port)
        while not self.exit:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(server_address)
                sock.settimeout(None)
            except socket.error as e:
                print ("Binding: ERROR - " + str(e))
                sock = None
                time.sleep(CONN_TIMEOUT)
            else:
                break # continue because binding is done
        while not self.exit:
            print ("Waiting for incoming socket connection to port " + str(self.port) + " on this device")
            try:
                sock.listen(1)
                self.sock, client_address = sock.accept()
                self.client = client_address[0] + ":" + str(client_address[1])
                self.sock.settimeout(None)
            except socket.error as e:
                self.sock = None
                time.sleep(CONN_TIMEOUT)
            else:
                print ("'" + self.client + "': Connected to port " + str(self.port) + " on this device")
                self.isAtive = True
                break # continue because connection is done
        return

#---------------------------------------------------------------------------------
# this is the code to be executed to send a message
    def send(self, msg):
        while (not self.isAtive) and (not self.exit):
            time.sleep(1) # wait until active or to exit
        if self.isAtive:
            #print ("To '" + self.client + "', sending message:", msg)
            msg = msg + "|"
            self.sock.sendall(msg.encode()) # add end of command delimiter
        return

#---------------------------------------------------------------------------------
# this is the code to be executed to close the socket and exit (usually not used on raspberry pi - just turn off the power)
    def stop(self):
        print ("'" + self.client + "': Stop the socket thread - closing socket")
        try:
            self.sock.close()
        except: # ignore possible error if connection not ok
            pass
        finally:
            self.isAtive = False
            self.exit = True
        return

#*********************************************************************************

inputArgs = sys.argv
if len(inputArgs) > 1:
    try:
        port = int(inputArgs[1])
    except: # invalid port
        port = 14200 # default
else:
    port = 14200 # default
sock = serverTcpThread(serverTcpThread_callback(), port)
sock.start()
while True:
    pass
