################################################################################
# This script is run within JMRI, as part of the statup sequence. The goal of this script
# is to initialize the layout by setting all the turnouts to CLOSED position. It also
# sets up the different virual masts (tied to the end of the track) to CLEAR, unless there
# is a train blocking one of the end of line sensors. 
# The script also sets up Sensor Listeners that will allow the virutal signal masts to be set
# to DANGER, or CLEAR depending on the end of line sensor status.  
# The sequence in which this script is run within the startup sequence makes a huge 
# difference. It has to be run after we initialize the JMRI_Script_V2, as we need the 
# TCPPeripheal to be active before we initialize anyt of these things. 
################################################################################

import jmri
import java
import java.beans
import time

# get gpio and id from turnout or sensor system name
def getSensorGpioId(sysName):
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
    
# Set the virtual mast connected to an end of track sensor to DANGER
def getVirtualMast(sensor):
    signalMast = None
    _sensorName = sensor.getSystemName()
    _gpio, _id = getSensorGpioId(_sensorName)
    
    if _gpio != None:
        _virtualSignalMast = "SM" + str(_gpio) + "v" # Build the appropriate virtual mast name
        _signalmast = masts.getByUserName(_virtualSignalMast) 
        if _signalmast != None:
            signalMast = _signalmast
    return signalMast

################################################################################
# define the listener class for Sensors
class Sensor_Listener(java.beans.PropertyChangeListener):

    def propertyChange(self, event):
        _sensor = event.getSource()
        if event.newValue == jmri.Sensor.ACTIVE: # only this property matters
            _virtualSignalMast = getVirtualMast(_sensor)
            if _virtualSignalMast != None:
                _virtualSignalMast.setAspect("Stop")
                #print "Setting " + _virtualSignalMast.getSystemName() + " to Stop"
        if event.newValue == jmri.Sensor.INACTIVE: # only this property matters
            _virtualSignalMast = getVirtualMast(_sensor)
            if _virtualSignalMast != None:
                _virtualSignalMast.setAspect("Clear")
                #print "Setting " + _virtualSignalMast.getSystemName() + " to Clear"
        return



################################################################################
# This is the main running class; its a derived class of the Automaton object
class initializeLayout(jmri.jmrit.automat.AbstractAutomaton):      
  
    # Init does nothing in particular
    def init(self):
        return

    # Handle is called when the class's start() is invoked
    # Handle does the initializations including
    # 1. Set all turnouts to CLOSED
    # 2. Sets all the virtual signals (at the end of the rails) to CLEAR
    # 3. In case one of the locomotives is at the end of the track, set that virtual signal to DANGER
    def handle(self):

        # Initialize all the Signal Heads to RED, but first set it to DARK to remove the internal memory
        for signal in signals.getNamedBeanSet():
            signal.setAppearance(jmri.SignalHead.DARK)
        for signal in signals.getNamedBeanSet():
            signal.setAppearance(jmri.SignalHead.RED)

        
        # Iterate over all the turnouts and set them to CLOSED
        for turnout in turnouts.getNamedBeanSet():
            # focus on only turnouts that are controlled by the Pi
            if "PI3BMODELTRAIN" in turnout.getSystemName():
                currentState = turnout.getCommandedState()
                if currentState != jmri.Turnout.CLOSED:
                    #print "Setting " + turnout.getSystemName() + " turnout to CLOSED"
                    turnout.setCommandedState(jmri.Turnout.CLOSED)
            self.waitMsec(50)

        # Iterate over every signal mast and set the virtual Signal masts to CLEAR
        for signalmast in masts.getNamedBeanSet():
            if "v" in signalmast.getUserName():
                #print "Setting " + signalmast.getUserName() + " signal mast to Clear"
                signalmast.setAspect("Clear")
        
        # Iterate over every sensor to pick the end of line sensors
        for sensor in sensors.getNamedBeanSet():
            # focus on only sensors that are controlled by Pi
            if "PI3BMODELTRAIN" in sensor.getSystemName():
                # See if there is a virtual mast associated with the sensor
                virtualSigMast = getVirtualMast(sensor)
                if virtualSigMast != None: 
                    #print "Setting " + sensor.getSystemName() + " property change listener"
                    # Setup listener for that sensor with its virtual mast
                    sensor.addPropertyChangeListener(Sensor_Listener())
                    # Check if there is already an active sensor, if so, set the virual mast to Danger
                    if sensor.getCommandedState() == jmri.Sensor.ACTIVE:
                        virtualSigMast.setAspect("Stop") # Set the apperance to Dark
        
        return False              # all done, don't repeat again
    

##########################################################################################
# Main section of the code

# Initialization class adbstracted from the Automaton java class
initializeLayout().start()         


