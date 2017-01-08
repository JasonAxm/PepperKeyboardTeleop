# -*- coding: utf-8 -*-
'''
 Copyright (c) 2017, Jason Yang. All rights reserved.
 Use of this source code is governed by a BSD-style license that can be
 found in the COPYING file.
'''
import pythoncom
import pyHook
import qi
import argparse
import sys
import almath
import time
import json
import ctypes
import threading 

helpInfo = """
Control Pepper robot!
---------------------------
Moving around:
   u    i    o
   j    k    l
   m    ,    .

Y-orientation moving£º
   'a' move toward left
   'd' move toward right

Head moving:
       Up
  Left     Right
      Down
      
q/z : increase/decrease max speeds by 10%
w/x : increase/decrease only linear speed by 10%
e/c : increase/decrease only angular speed by 10%
space key, k, s: force stop
anything else : stop smoothly

ESC to quit
"""
'''
left:37
right:39
up:38
Down:40
'''
g_headMoveBingdings={
"37":["HeadYaw",0.2],
"39":["HeadYaw",-0.2],
"38":["HeadPitch",-0.2],
"40":["HeadPitch",0.2],
}

g_moveBindings = {
        'i':(1,0,0),
        'o':(1,-1,0),
        'j':(0,0,1),
        'l':(0,0,-1),
        'u':(1,1,0),
        ',':(-1,0,0),
        '.':(-1,1,0),
        'm':(-1,-1,0),
        'a':(0,1,0),
        'd':(0,-1,0)
        }

g_speedBindings={
        'q':(1.1,1.1),
        'z':(.9,.9),
        'w':(1.1,1),
        'x':(.9,1),
        'e':(1,1.1),
        'c':(1,.9),
        }

g_defaultMoveConfig = {
        "MaxVelXY":0.35,
        "MaxVelTheta":1.0,
        }
        
g_maxLinearSpeed = 0.55
g_maxAngularSpeed = 2.0

def FlushInfo(infoStr):
    sys.stdout.write(infoStr + "\r")
    sys.stdout.flush()
    
@qi.multiThreaded()
class EventHelper:

    def __init__(self, memory, subscribers):
        self.subscribers    = subscribers
        self.memory         = memory
        self.serviceName    = "landmarkEventHelper"
        self.subscribeToggle= False
        self.connectSubscribers()

    @qi.bind()
    def connectSubscribers(self):
        """ generate & connect all subscribers to callbacks """
        if not self.subscribeToggle:
            for event in self.subscribers.keys():
                self.subscribers[event]["subscriber"] = self.memory.subscriber(event)
                self.subscribers[event]["uid"]        = self.subscribers[event]["subscriber"].signal.connect(self.subscribers[event]["callback"])
            self.subscribeToggle = True

    @qi.bind()
    def disconnectSubscribers(self):
        """ disconnect all subscribers from callbacks """
        qi.info(self.serviceName, "DISCONNECTING SUBSCRIBERS")
        if self.subscribeToggle:
            for event in self.subscribers.keys():
                future = qi.async(self.disconnectSubscriber, event, delay = 0)
                future.wait(1000) # add a timeout to avoid deadlock
                if not future.isFinished():
                    qi.error(self.serviceName, "disconnectSubscribers", "Failed disconnecting %s subscribers" % event)
            self.subscribeToggle = False   
            
class PepperKeyboardControl(object):

    def __init__(self, app):
        app.start()
        self.session = app.session
        self.motion  = self.session.service("ALMotion")
        self.posture = self.session.service("ALRobotPosture")
        self.memory = self.session.service("ALMemory")
        
        self.application_name = "PepperKeyboardControl"
        self.logger = qi.Logger(self.application_name)     
        
        self.moveConfig = g_defaultMoveConfig
        self.currentToward = []
        self.forceStop = False
        self.smoothStopping = False
        
        self.controlEvents = {"moveToward": "pepperTeleop/moveToward",
                               "stopSmoothly":"pepperTeleop/stopSmoothly",
                               "moveHead":"pepperTeleop/moveHead",
                              } 
        self.subscribers = {
            self.controlEvents["moveToward"]: {"callback": self.moveTowardCB},
            self.controlEvents["stopSmoothly"]: {"callback": self.stopSmoothlyCB},
            self.controlEvents["moveHead"]:{"callback":self.moveHeadCB},
        }
        
        self.eventHelper = EventHelper(self.memory, self.subscribers)
    
    def getKeyData(self, key):
        x = g_moveBindings[key][0]
        y = g_moveBindings[key][1]
        theta = g_moveBindings[key][2]
        
        moveConfig = []
        for configKey in self.moveConfig.keys():
            moveConfig.append([configKey, self.moveConfig[configKey]])
        
        eventData = []
        eventData.append([x, y, theta])
        eventData.append(moveConfig)
        return eventData
        
    def onKeyUpEvent(self, event):
        key = chr(event.Ascii)
        if key in g_moveBindings.keys():
            eventData = self.getKeyData(key)
            self.memory.raiseEvent(self.controlEvents["stopSmoothly"], eventData)
        return True
        
    def onKeyDownEvent(self, event):
        # ¼àÌý¼üÅÌÊÂ¼þ
        if(event.KeyID == 27):
            ctypes.windll.user32.PostQuitMessage(0)
            return True
        '''
        print "MessageName:", event.MessageName   
        print "Message:", event.Message   
        print "Time:", event.Time   
        print "Window:", event.Window   
        print "WindowName:", event.WindowName   
        print "Ascii:", event.Ascii, chr(event.Ascii)   
        print "Key:", event.Key   
        print "KeyID:", event.KeyID   
        print "ScanCode:", event.ScanCode   
        print "Extended:", event.Extended   
        print "Injected:", event.Injected   
        print "Alt", event.Alt   
        print "Transition", event.Transition   
        print "---"   
        '''
        
        key = chr(event.Ascii)
        keyID = str(event.KeyID)
        
        if key in g_moveBindings.keys():
            if self.smoothStopping:
                return True
            eventData = self.getKeyData(key)
            self.memory.raiseEvent(self.controlEvents["moveToward"], eventData)
        elif keyID in g_headMoveBingdings.keys():
            self.memory.raiseEvent(self.controlEvents["moveHead"], g_headMoveBingdings[keyID])
        elif key == ' ' or key == 'k' or key == 's':
            FlushInfo("Force stop moving")
            self.forceStop = True
            self.smoothStopping  = False
            self.motion.stopMove()
        
        elif key in g_speedBindings.keys():
            self.moveConfig["MaxVelXY"] = self.moveConfig["MaxVelXY"]*g_speedBindings[key][0]
            self.moveConfig["MaxVelTheta"] = self.moveConfig["MaxVelTheta"]*g_speedBindings[key][1]
            if self.moveConfig["MaxVelXY"] >= g_maxLinearSpeed:
                self.moveConfig["MaxVelXY"] = g_maxLinearSpeed
            if self.moveConfig["MaxVelTheta"] >= g_maxAngularSpeed:
                self.moveConfig["MaxVelTheta"] = g_maxAngularSpeed
            info = "Setting pepper robot moving velocity is:['MaxVelXY':%f,'MaxVelTheta':%f]"%(
                    self.moveConfig["MaxVelXY"],self.moveConfig["MaxVelTheta"])
            FlushInfo(info)
        
        return True
    
    def moveHeadCB(self, operation):
        try:
            name = operation[0]
            angle = operation[1]
        except:
            FlushInfo("Input data for move head is error")
        '''TODO'''
        try:
            cmdAngles = self.motion.getAngles(name, False)
            snsAngles = self.motion.getAngles(name, True)
            angle = cmdAngles[0] + angle
        except:
            angle = angle
        FlushInfo("Set %s angle as %f"%(name, angle))
        fractionMaxSpeed  = 0.15
        self.motion.setAngles(name, angle, fractionMaxSpeed)
    
    def moveTowardCB(self, operation):
        try:
            toward = operation[0]
            moveConfig = operation[1]
            x = toward[0]
            y = toward[1]
            theta = toward[2]
        except:
            FlushInfo("Input operation data for movetoward is error")
            return False
            
        toward = operation[0]
        moveConfig = operation[1]
        if len(toward) < 3:
            return False
        info = "Move towards to [%d,%d,%d], move config[[\"%s\",%f],[\"%s\",%f]]"%(
                x, y, theta,
                moveConfig[0][0], moveConfig[0][1], 
                moveConfig[1][0], moveConfig[1][1])
        FlushInfo(info)
        ret = self.motion.moveToward(x, y, theta, moveConfig)        
        return True        
    
    def stopSmoothlyCB(self, operation):
        try:
            toward = operation[0]
            moveConfig = operation[1]
            x = toward[0]
            y = toward[1]
            theta = toward[2]
        except:
            FlushInfo("Input data is error")
            return False
            
        self.smoothStopping = True     
        time.sleep(1)
        if not self.forceStop:
            x = x*0.5
            y = y*0.5
            theta = theta*0.5
            self.motion.moveToward(x, y, theta, moveConfig)
        
        time.sleep(1)
        if not self.forceStop:  
            moveConfig[0][1] = moveConfig[0][1]*0.5
            moveConfig[1][1] = moveConfig[1][1]*0.5
            self.motion.moveToward(x, y, theta, moveConfig)
        
        time.sleep(1)
        if not self.forceStop:
            self.motion.stopMove()
            FlushInfo("Stopped smoothly")
        
        self.smoothStopping = False
        self.forceStop = False
        return True
    
    def run(self):
        hm = pyHook.HookManager()
        hm.KeyDown = self.onKeyDownEvent
        hm.KeyUp = self.onKeyUpEvent
        hm.HookKeyboard()

        print "Pepper keyboard teleopration start "
        pythoncom.PumpMessages()
        print "Pepper keyboard teleopration finished "

 
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", type=str, default="10.1.44.29",
                        help="Robot IP address. On robot or Local Naoqi: use '127.0.0.1'.")
    parser.add_argument("--port", type=int, default=9559,
                        help="Naoqi port number")

    args = parser.parse_args()
    try:
        # Initialize qi framework.
        connection_url = "tcp://" + args.ip + ":" + str(args.port)
        app = qi.Application(["PepperKeyboardControl", "--qi-url=" + connection_url])
    except RuntimeError:
        print ("Can't connect to Naoqi at ip \"" + args.ip + "\" on port " + str(args.port) +".\n"
               "Please check your script arguments. Run with -h option for help.")
        sys.exit(1)

    print helpInfo
    PepperKeyboardControl = PepperKeyboardControl(app)
    PepperKeyboardControl.run()
