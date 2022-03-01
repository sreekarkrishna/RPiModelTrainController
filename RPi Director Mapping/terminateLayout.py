################################################################################
# This script is run within JMRI, as part of the statup sequence. The goal of this script
# is to turn off all the Signal Head LEDs when JMRI is exiting. Makes it easier for 
# turning off the layout that way. 
# The sequence in which this script is run within the startup sequence makes a huge 
# difference. It has to be run before we initialize the JMRI_Script_V2, as we need the 
# TCPPeripheal to be active in the shutdown sequence. 
################################################################################


import jmri
import java
import java.beans
from org.apache.log4j import Logger

TcpPeripheral_log = Logger.getLogger("jmri.jmrit.jython.exec.TcpPeripheral")

################################################################################
# define the shutdown task class
# Before shutting down, turn off all the signal heads
class Layout_ShutDown(jmri.implementation.AbstractShutDownTask):

    # this is the code to be invoked when the program is shutting down
    # Set all the signal heads to Dark
    def execute(self):
        TcpPeripheral_log.info("Shutting down Layout")
        for signal in signals.getNamedBeanSet():
            signal.setAppearance(jmri.SignalHead.DARK) # 0 is the int equivilent for Dark
            #print "Setting " + signal.getSystemName() + " signal head to DARK"
        for turnout in turnouts.getNamedBeanSet():
            turnout.setCommandedState(jmri.Turnout.CLOSED)
        return True

##########################################################################################
# Main section of the code

# Register the shutdown task, which is abstracted from the java Shutdown task class
shutdown.register(Layout_ShutDown("Shutdown Layout"))