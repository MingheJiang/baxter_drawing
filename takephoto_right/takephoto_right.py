#!/usr/bin/env python

import rospy
import roslib
import csv
import cv
import cv2
from cv_bridge import CvBridge, CvBridgeError
import copy
import struct
import numpy
import math
import os
import sys
from pylab import *
import string
import time
import random
from scipy import interpolate
import tf
import cv_bridge
import argparse
import image_geometry
from sensor_msgs.msg import Image
import baxter_interface
from geometry_msgs.msg import PointStamped, PoseStamped, Pose, Point, Quaternion,Transform
from std_msgs.msg import Header
import std_srvs.srv
from baxter_core_msgs.srv import SolvePositionIK, SolvePositionIKRequest
from sensor_msgs.msg import JointState
from baxter_interface import CHECK_VERSION
import numpy as np
from sensor_msgs.msg import CameraInfo
# initialise ros node
rospy.init_node("rcam")

# directory used to save analysis images
image_directory = os.getenv("HOME") + "/home/minghe/baxter_drawing/takephoto_right/"

# locate class
class locate():
    #initialization function: limb used, gripper, tolerences, workspace, vision parameters, start position
    def __init__(self, arm, distance):
        global image_directory
        #Interface class for a limb on the Baxter robot.
        # arm ("left" or "right")
        self.limb           = arm
        self.limb_interface = baxter_interface.Limb(self.limb)

        if arm == "left":
            self.other_limb = "right"
        else:
            self.other_limb = "left"

        self.other_limb_interface = baxter_interface.Limb(self.other_limb)
        
        self.bridge = CvBridge()
        
        # gripper ("left" or "right")
        self.gripper = baxter_interface.Gripper(arm)

        # image directory
        self.image_dir = image_directory

        # flag to control saving of analysis images
        self.save_images = True


        # camera parameters (NB. other parameters in open_camera)
        self.cam_calib    = 0.0025                     # meters per pixel at 1 meter
        self.cam_x_offset = 0                      # camera gripper offset
        self.cam_y_offset = -0.025
        self.width        = 480#480 640                       # Camera resolution
        self.height       = 300#300 400
        self.canny = cv.CreateImage((self.width, self.height), 8, 1)
        # Canny transform parameters
        self.robotposition=JointState()
        
        # start positions
        
        self.paper_x = 0.77                       
        self.paper_y = -0.451769                       
        self.paper_z = 0.1                                           
        self.roll        = -1.0 * math.pi             
        self.pitch       = 0.0 * math.pi              
        self.yaw         = 0.0 * math.pi               
        
        self.running = 0 # flag for running self.canny()
        
        self.pose = [self.paper_x, self.paper_y, self.paper_z,     \
                     self.roll, self.pitch, self.yaw]           
        # callback image
        self.cv_image = cv.CreateImage((self.width, self.height), 8, 3)

        # distance of arm to table and ball tray
        self.distance      = distance 
        self.tray_distance = distance 
        
        # Enable the actuators
        baxter_interface.RobotEnable().enable()

        # create image publisher to head monitor
        self.pub = rospy.Publisher('lcampub', Point, queue_size=10)

        # reset cameras
        self.reset_cameras()       

        # open required camera
        self.open_camera(self.limb, self.width, self.height) # open camera on the limb in motion only via function below

    def list_to_pose_stamped(self, pose_list, target_frame):
        pose_msg = PoseStamped()
        pose_msg.pose = self.list_to_pose(pose_list)
        pose_msg.header.frame_id = target_frame
        pose_msg.header.stamp = rospy.Time.now()
        return pose_msg        
    
    def list_to_pose(self, pose_list):
        pose_msg = Pose()
        if len(pose_list) == 6: 
            pose_msg.position.x = pose_list[0]
            pose_msg.position.y = pose_list[1]
            pose_msg.position.z = pose_list[2]
            q = tf.transformations.quaternion_from_euler(pose_list[3], pose_list[4], pose_list[5])
            pose_msg.orientation.x = q[0]
            pose_msg.orientation.y = q[1]
            pose_msg.orientation.z = q[2]
            pose_msg.orientation.w = q[3]
        else:
            raise MoveItCommanderException("Expected either 6 or 7 elements in list: (x,y,z,r,p,y) or (x,y,z,qx,qy,qz,qw)")
        return pose_msg 

    # reset all cameras (incase cameras fail to be recognised on boot)
    def reset_cameras(self):
        reset_srv = rospy.ServiceProxy('cameras/reset', std_srvs.srv.Empty)
        rospy.wait_for_service('cameras/reset', timeout=10)
        reset_srv()

    # open a camera and set camera parameters
    def open_camera(self, camera, x_res, y_res):
        if camera == "left":
            cam = baxter_interface.camera.CameraController("left_hand_camera")
        elif camera == "right":
            cam = baxter_interface.camera.CameraController("right_hand_camera")
        elif camera == "head":
            cam = baxter_interface.camera.CameraController("head_camera")
        else:
            sys.exit("ERROR - open_camera - Invalid camera")

        # set camera parameters
        print (int(x_res), int(y_res))
        cam.resolution          = (int(x_res), int(y_res))
        cam.exposure            = -1             
        cam.gain                = -1             
        cam.white_balance_blue  = -1             
        cam.white_balance_green = -1             
        cam.white_balance_red   = -1             

        # open camera
        cam.open()

    # close a camera
    def close_camera(self, camera):
        if camera == "left":
            cam = baxter_interface.camera.CameraController("left_hand_camera")
        elif camera == "right":
            cam = baxter_interface.camera.CameraController("right_hand_camera")
        elif camera == "head":
            cam = baxter_interface.camera.CameraController("head_camera")
        else:
            sys.exit("ERROR - close_camera - Invalid camera")

        # set camera parameters to automatic
        cam.exposure            = -1             # range, 0-100 auto = -1
        cam.gain                = -1             # range, 0-79 auto = -1
        cam.white_balance_blue  = -1             # range 0-4095, auto = -1
        cam.white_balance_green = -1             # range 0-4095, auto = -1
        cam.white_balance_red   = -1             # range 0-4095, auto = -1

    def node1cb(self, data, args ):
        
        bridge = args[0]
        pub = args[1]
        
        try:
            self.cv_image = bridge.imgmsg_to_cv2(data, "bgr8")
        except CvBridgeError, e:
            print("==[CAMERA MANAGER]==", e)
        
        cv2.waitKey(3)
        cv2.imshow('newframe',self.cv_image)
        
        if self.running == 0:
            self.canny_it()
        
        
    # Convert cv image to a numpy array
    def cv2array(self, im):
        depth2dtype = {cv.IPL_DEPTH_8U: 'uint8',
                       cv.IPL_DEPTH_8S: 'int8',
                       cv.IPL_DEPTH_16U: 'uint16',
                       cv.IPL_DEPTH_16S: 'int16',
                       cv.IPL_DEPTH_32S: 'int32',
                       cv.IPL_DEPTH_32F: 'float32',
                       cv.IPL_DEPTH_64F: 'float64'}
  
        arrdtype=im.depth
        a = numpy.fromstring(im.tostring(),
                             dtype = depth2dtype[im.depth],
                             count = im.width * im.height * im.nChannels)
        a.shape = (im.height, im.width, im.nChannels)

        return a
    
    def canny_it(self):
        length_m = 0
        while length_m < 30 :
            
            gray = cv.CreateImage((cv.GetSize(cv.fromarray(self.cv_image))), 8, 1)
          
            cv.CvtColor(cv.fromarray(self.cv_image), gray, cv.CV_BGR2GRAY)

            edges = cv2.Canny(self.cv2array(gray),50,100,apertureSize = 3)
            
            for count in range(2):
                cv2.imwrite('cannyedge_after.jpg',edges)
                img = cv2.imread('cannyedge_after.jpg')
                imgray = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
                ret,thresh = cv2.threshold(imgray,200,255,0)
                contours,hierarchy = cv2.findContours(thresh, cv2.RETR_TREE,cv2.CHAIN_APPROX_SIMPLE)
                cnt = contours[0]
                M = cv2.moments(cnt)
                x,y,w,h = cv2.boundingRect(cnt)
                cv2.rectangle(img,(x,y),(x+w,y+h),(0,255,0),2)
                centerx = x+0.5*w
                centery = y+0.5*h
                next = self.pixel_to_baxter((centerx,centery),self.tray_distance)          
                pose = (next[0],next[1],self.paper_z,self.roll,self.pitch,self.yaw)
                self.baxter_ik_move(self.limb, pose)  
                        
            final_x = baxter_interface.Limb('right').endpoint_pose()['position'].x 
            final_y = baxter_interface.Limb('right').endpoint_pose()['position'].y  
            #print final_x, final_y 
            
            self.trans_x = 0.635 - final_x #tranfer from right hand work space to left hand
            self.trans_y = 0.65 - final_y
            #print self.trans_x,self.trans_y
            cv2.imwrite('cannyedge_after.jpg',edges)
            if self.save_images:
                file_name = self.image_dir                                                 \
                              + "origin" + ".jpg"
                cv.SaveImage(file_name, cv.fromarray(self.cv_image))

            gray = cv.CreateImage((cv.GetSize(cv.fromarray(self.cv_image))), 8, 1)        
            cv.CvtColor(cv.fromarray(self.cv_image), gray, cv.CV_BGR2GRAY)
            edges = cv2.Canny(self.cv2array(gray),50,100,apertureSize = 3)
            cv2.imwrite('cannyedge_after.jpg',edges)
            img = cv2.imread('cannyedge_after.jpg')
            imgray = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
            ret,thresh = cv2.threshold(imgray,200,255,0)
            contours,hierarchy = cv2.findContours(thresh, cv2.RETR_TREE,cv2.CHAIN_APPROX_SIMPLE)
            cnt = contours[0]
            M = cv2.moments(cnt)
            x,y,w,h = cv2.boundingRect(cnt)
            cv2.rectangle(img,(x,y),(x+w,y+h),(0,255,0),2)   
            cv2.imwrite('rect.jpg',img)
        

            img = cv2.imread('cannyedge_after.jpg')
            gray = cv2.GaussianBlur(img,(3,3),3)
            se = 7
            kernel1 = np.ones((se,se),np.uint8)
            kernel2 = np.ones((se+2,se+2),np.uint8)
            kernel3 = np.ones((4,4),np.uint8)
            kernel4 = np.ones((1,1),np.uint8)
            dilation = cv2.dilate(gray,kernel1,iterations = 1)
            cv2.imwrite('dilation.jpg',dilation)
            out = cv2.erode(dilation,kernel2,iterations = 1)
            out = cv2.erode(out,kernel3,iterations = 1)
            for i in range(80):
                out = cv2.erode(out,kernel4,iterations = 1)        
            cv2.imwrite('erode.jpg',out)
            gray = cv2.cvtColor(out,cv2.COLOR_BGR2GRAY)
            minLineLength = 95
            maxLineGap = 15
            lines = cv2.HoughLinesP(gray,4,np.pi/180,200,minLineLength,maxLineGap)
            length_m = lines.shape[1]
            
        point_data = []
        for x1,y1,x2,y2 in lines[0]:
            cv2.line(img,(x1,y1),(x2,y2),(0,255,0),1)
            line_points1 = self.pixel_to_baxter_left((x1,y1),self.tray_distance)
            line_points2 = self.pixel_to_baxter_left((x2,y2),self.tray_distance)
            line_points1 = np.array(line_points1)
            line_points2 = np.array(line_points2)
            point_data.append(line_points1)
            point_data.append(line_points2)
        cv2.imwrite('houghlines.jpg',img)
        point_data = np.asarray(point_data)
        point_data.shape = (len(point_data),2)
        x = asarray(point_data[:,0])
        x.shape = (size(x),1)
        y = asarray(point_data[:,1])
        y.shape = (size(y),1)        
        q = []
        for i in range(len(x)):
            q.append(x[i])
            q.append(y[i])
        q = asarray(q)
        q.shape = (len(x),2) 
        q = list(q)
        last = []
        last.append(x[0])
        last.append(y[0])
        last = asarray(last)
        last.shape = (1,2) 
        last = list(last)      
           
        point = []
        point.append(q[0])
        
        example=csv.writer(open('test_origin.csv', 'wb'), delimiter=',')
        
        example.writerows(point_data) 
        q.pop(0)
        i = 0
        target_count = 1 
        length = copy(len(q))
        
        while i < length:
            if i < len(q)/2:
                dist  = 100000000   
                for j in range (0,len(q)):
                    dist_temp = math.hypot(q[j][0]-point[i][0], q[j][1]-point[i][1]) 
                     
                    if  dist_temp < dist:
                        dist = dist_temp
                        target_count  = j 
                point.append(q[target_count])
            else:
                dist  = 100000000   
                for j in range (0,len(q)):
                    dist_temp = math.hypot(q[j][0]-point[i][0], q[j][1]-point[i][1])  
                    if  dist_temp < dist:
                        dist = dist_temp
                        target_count  = j
                if dist >  math.hypot(point[i][0]-x[0][0], point[i][1]-y[0][0]):
                    i = length +1
                    
                else:
                    i = i
                    point.append(q[target_count]) 
                   
            
            
            i = i + 1
            q.pop(target_count)

        point.append(last[0])
    
        point = np.asarray(point)
        point.shape = (len(point),2)
        point_z = []
        for i in range(len(point)):
            point_z.append(0.18)
        point_z = np.asarray(point_z)
        point_z.shape = (len(point),1)   
        example=csv.writer(open('test_left_origin.csv', 'wb'), delimiter=',')
        data = np.hstack((point,point_z))
        example.writerows(data)
        
        x = point[:,0]
        y = point[:,1]   
        tck,u=interpolate.splprep([x,y],s=0,k=1)

        x_i,y_i= interpolate.splev(np.linspace(0,1,26),tck)
        x_i = np.asarray(x_i)
        x_i.shape = (len(x_i),1)   
        y_i = np.asarray(y_i)
        y_i.shape = (len(y_i),1)         
        point_z = []

        for i in range(len(x_i)):
            point_z.append(0.18)
        point_z = np.asarray(point_z)
        point_z.shape = (len(x_i),1)   
        example=csv.writer(open('test_left_spline.csv', 'wb'), delimiter=',')
        data = np.hstack((x_i,y_i,point_z))
        example.writerows(data)        
     
        self.running =1
        cv.WaitKey(3)
    
    # convert image pixel to Baxter point
    def pixel_to_baxter(self, px, dist):
        x = ((px[1] - (self.height / 2)) * self.cam_calib * 0.2)                \
          + self.pose[0] 
        
        y = ((px[0] - (self.width / 2)) * self.cam_calib * 0.2)                 \
          + self.pose[1] 
        return (x, y)
    def pixel_to_baxter_left(self, px, dist):
        x = ((px[1] - (self.height / 2)) * self.cam_calib * 0.2)                \
          + self.pose[0] + self.cam_x_offset + self.trans_x
        y = ((px[0] - (self.width / 2)) * self.cam_calib * 0.2)                 \
          + self.pose[1] + self.cam_y_offset + self.trans_y
        return (x, y) 


    # move a limb
    def baxter_ik_move(self, limb, rpy_pose):
        quaternion_pose = self.list_to_pose_stamped(rpy_pose, "base")
        node = "ExternalTools/" + limb + "/PositionKinematicsNode/IKService"
        ik_service = rospy.ServiceProxy(node, SolvePositionIK)
        ik_request = SolvePositionIKRequest()
        hdr = Header(stamp=rospy.Time.now(), frame_id="base")

        iterate_IK = True 
        n_iterations = 0
        ik_request.pose_stamp.append(quaternion_pose)
        while iterate_IK:
            try:
                rospy.wait_for_service(node, 5.0)
                ik_response = ik_service(ik_request)
            except (rospy.ServiceException, rospy.ROSException), error_message:
                rospy.logerr("Service request failed: %r" % (error_message,))
                sys.exit("ERROR - baxter_ik_move - Failed to append pose")

            if ik_response.isValid[0]:
                print("PASS: Valid joint configuration found")
                # convert response to joint position control dictionary
                limb_joints = dict(zip(ik_response.joints[0].name, ik_response.joints[0].position))
                # move limb
                if self.limb == limb:
                    self.limb_interface.move_to_joint_positions(limb_joints)
                else:
                    self.other_limb_interface.move_to_joint_positions(limb_joints)
                iterate_IK = False
            else:

                currentJointState = rospy.wait_for_message("/robot/joint_states",JointState)
                newJointState=copy.copy(currentJointState)

                seed_angle_val=JointState()
                seed_angle_val.header.stamp = rospy.Time.now()
                current_angle = []
                name_val = []
                for i in range (2,9):
                    temp_name = copy.copy(currentJointState.name[i])
                    temp_angle = copy.copy(currentJointState.position[i])
                    temp_angle = temp_angle+(random.random()-0.5)/10
                    name_val.append(temp_name)
                    current_angle.append(temp_angle)
                
                seed_angle_val.name=name_val
                seed_angle_val.position=current_angle

                seed_angle_list=[seed_angle_val]
 
                ik_request.seed_angles = seed_angle_list
                n_iterations=n_iterations+1
                print n_iterations

            
            if n_iterations > 50:
                # display invalid move message on head display
                self.splash_screen("Invalid IK", "Solution")
                #sys.exit("ERROR - baxter_ik_move - No valid joint configuration found")
                print 'IK did not converge after %d iterations' %n_iterations
                return 

        if self.limb == limb:               # if working arm
            quaternion_pose = self.limb_interface.endpoint_pose()
            position        = quaternion_pose['position']

            # if working arm remember actual (x,y) position achieved
            self.pose = [position[0], position[1],                                \
                         self.pose[2], self.pose[3], self.pose[4], self.pose[5]]

# read the setup parameters from setup.dat
def get_setup():
    global image_directory
    
    file_name = image_directory + "setup.dat"

    try:
        f = open(file_name, "r")
    except ValueError:
        sys.exit("ERROR: setup.py must be run before this file")

    # find limb
    s = string.split(f.readline())
    if len(s) >= 3:
        if s[2] == "left" or s[2] == "right":
            limb = s[2]
        else:
            sys.exit("ERROR: invalid limb in %s" % file_name)
    else:
        sys.exit("ERROR: missing limb in %s" % file_name)

    # find distance to table
    s = string.split(f.readline())
    if len(s) >= 3:
        try:
            distance = float(s[2])
        except ValueError:
            sys.exit("ERROR: invalid distance in %s" % file_name)
    else:
        sys.exit("ERROR: missing distance in %s" % file_name)

    return limb, distance

def main():
    right = baxter_interface.Limb('right')
    limb, distance = get_setup()
    print "limb     = ", limb
    print "distance = ", distance
    distance +=(.03)

    locator = locate(limb, distance)
    locator.pose = (right.endpoint_pose()['position'].x,
                    right.endpoint_pose()['position'].y,
                    locator.paper_z,
                    locator.roll,
                    locator.pitch,
                    locator.yaw)

    locator.camera_sub = rospy.Subscriber('/cameras/right_hand_camera/image', Image, locator.node1cb, callback_args=(locator.bridge, locator.pub))    
if __name__ == "__main__":
    main()
    print 'here before spin'
    rospy.spin()



