# Sample script to add a button to the PanelPro Window
# JMRI application window that loads a script file
#
# Author: Bob Jacobsen, copyright 2007
# Modified: Sreekar Krishna, copyright 2021
# Part of the JMRI distribution

#
# NOTE: The recommended way to add a script button to JMRI is to
# use the Startup Items preferences to add that button.
#
# NOTE: This script does not support DecoderPro. Use the recommended
# method if you need to add a script to a button in DecoderPro.
#

import jmri
import javax.swing.JButton
import apps

# create the button, and add an action routine to it
buttonObj = javax.swing.JButton("Shutdown Layout and Exit")

def whenMyButtonClicked(event) :
    # run a script file
    execfile("/home/pi/Documents/RPiLayoutControllerV2/src/terminateLayout.py")
    return

buttonObj.actionPerformed = whenMyButtonClicked

# add the button to the main screen
apps.Apps.buttonSpace().add(buttonObj)

# force redisplay
apps.Apps.buttonSpace().revalidate()