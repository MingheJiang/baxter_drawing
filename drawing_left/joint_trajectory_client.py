#!/usr/bin/env python

"""
Baxter RSDK Joint Trajectory Action Client Example
"""
import argparse
import struct
import sys
import tf
import math
import threading 
import csv
import os
from cv_bridge import CvBridge, CvBridgeError
from copy import copy
import rospy
import numpy as np
import actionlib
import roslib
import string
import time
from pylab import *
from control_msgs.msg import (
    FollowJointTrajectoryAction,
    FollowJointTrajectoryGoal,
)
from geometry_msgs.msg import (
    PoseStamped,
    Pose,
    Point,
    Quaternion,
)
from trajectory_msgs.msg import (
    JointTrajectoryPoint,
)
from baxter_core_msgs.srv import (
    SolvePositionIK,
    SolvePositionIKRequest,
)

import baxter_interface
from std_msgs.msg import Header
from std_msgs.msg import UInt8
from baxter_interface import CHECK_VERSION
from sensor_msgs.msg import (JointState,
)
image_directory = os.getenv("HOME") + "/home/minghe/baxter_drawing/drawing_left/"
class locate():

    def __init__(self, arm, distance):
        global image_directory

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
        
        self.robotposition=JointState()
        
        # start positions
        self.roll        = -1.0 * math.pi              # roll  = horizontal
        self.pitch       = 0.0 * math.pi               # pitch = vertical
        self.yaw         = 0.0 * math.pi               # yaw   = rotation 

        self.running = 0 # flag for running self.canny()          

        self.distance      = distance #distance found by running the setup file
        self.tray_distance = distance #- 0.075
        
        # Enable the actuators
        baxter_interface.RobotEnable().enable()
    
    def load_data(self,a,n,m,g):
        # load data
        data = matrix(genfromtxt(a, delimiter=','))
        x = asarray(data[:,n])
        x.shape = (size(x),1)
        y = asarray(data[:,m])
        y.shape = (size(y),1)
        z = asarray(data[:,g])
        z.shape = (size(z),1)
        return (x,y,z)

    
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
                limb_joints = list(ik_response.joints[0].position)
                limb_joints1 = dict(zip(ik_response.joints[0].name, ik_response.joints[0].position))
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
                
                print 'IK did not converge after %d iterations' %n_iterations
                return 

        if self.limb == limb:               # if working arm
            quaternion_pose = self.limb_interface.endpoint_pose()
            position        = quaternion_pose['position']

            # if working arm remember actual (x,y) position achieved
            self.pose = [position[0], position[1],                                \
                         self.pose[2], self.pose[3], self.pose[4], self.pose[5]]
        return limb_joints
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


class Trajectory(object):
    def __init__(self, limb):
        ns = 'robot/limb/' + limb + '/'
        self._client = actionlib.SimpleActionClient(
            ns + "follow_joint_trajectory",
            FollowJointTrajectoryAction,
        )
        self._goal = FollowJointTrajectoryGoal()
        self._goal_time_tolerance = rospy.Time(0.1)
        self._goal.goal_time_tolerance = self._goal_time_tolerance
        server_up = self._client.wait_for_server(timeout=rospy.Duration(10.0))
        if not server_up:
            rospy.logerr("Timed out waiting for Joint Trajectory"
                         " Action Server to connect. Start the action server"
                         " before running example.")
            rospy.signal_shutdown("Timed out waiting for Action Server")
            sys.exit(1)
        self.clear(limb)

    def add_point(self, positions, time):
        point = JointTrajectoryPoint()
        point.positions = copy(positions)
        point.time_from_start = rospy.Duration(time)
        self._goal.trajectory.points.append(point)

    def start(self):
        self._goal.trajectory.header.stamp = rospy.Time.now()
        self._client.send_goal(self._goal)

    def stop(self):
        self._client.cancel_goal()

    def wait(self, timeout):
        self._client.wait_for_result(timeout=rospy.Duration(timeout))

    def result(self):
        return self._client.get_result()

    def clear(self, limb):
        self._goal = FollowJointTrajectoryGoal()
        self._goal.goal_time_tolerance = self._goal_time_tolerance
        self._goal.trajectory.joint_names = [limb + '_' + joint for joint in \
            ['s0', 's1', 'e0', 'e1', 'w0', 'w1', 'w2']]


def main():
    """RSDK Joint Trajectory Example: Simple Action Client

    Creates a client of the Joint Trajectory Action Server
    to send commands of standard action type,
    control_msgs/FollowJointTrajectoryAction.

    Make sure to start the joint_trajectory_action_server.py
    first. Then run this example on a specified limb to
    command a short series of trajectory points for the arm
    to follow.
    """
    global left
    global right
    arg_fmt = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(formatter_class=arg_fmt,
                                     description=main.__doc__)
    required = parser.add_argument_group('required arguments')
    required.add_argument(
        '-l', '--limb', required=True, choices=['left', 'right'],
        help='send joint trajectory to which limb'
    )
    args = parser.parse_args(rospy.myargv()[1:])
    limb = args.limb

    print("Initializing node... ")
    rospy.init_node("rsdk_joint_trajectory_client_%s" % (limb,))
    print("Getting robot state... ")
    rs = baxter_interface.RobotEnable(CHECK_VERSION)
    print("Enabling robot... ")
    rs.enable()
    print("Running. Ctrl-c to quit")

    

    limb, distance = get_setup()
    print "limb     = ", limb
    print "distance = ", distance
    distance +=(.03)

    locator = locate(limb, distance)  
    
    line_x,line_y,line_z = locator.load_data('test_left_spline.csv',0,1,2)      

    traj = Trajectory(limb)
    rospy.on_shutdown(traj.stop)
    # Command Current Joint Positions first
    limb_interface = baxter_interface.limb.Limb(limb)
    current_angles = [limb_interface.joint_angle(joint) for joint in limb_interface.joint_names()]
    traj.add_point(current_angles, 0.0)

    locator.pose = ((line_x[0].tolist())[0],
                (line_y[0].tolist())[0],
                (line_z[0].tolist())[0],
                locator.roll,
                locator.pitch,
                locator.yaw)
    p1 = locator.baxter_ik_move(locator.limb, locator.pose) 
    
    
    traj.add_point(p1, 10.0)    
    traj.start()
    
    traj.wait(15.0)
 
    idealx = []
    idealy = []  
    traj.add_point(current_angles, 0.0) 
    for i in range(len(line_x)):
        locator.pose = ((line_x[i].tolist())[0],
                    (line_y[i].tolist())[0],
                    (line_z[i].tolist())[0]-0.002,
                    locator.roll,
                    locator.pitch,
                    locator.yaw) 
        print locator.pose
        idealx.append(locator.pose[0])
        idealy.append(locator.pose[1])
        p = locator.baxter_ik_move(locator.limb, locator.pose)

        traj.add_point(p, 1.6*i)             
    example=csv.writer(open('test_ideal.csv', 'wb'), delimiter=',')
    idealx = asarray(idealx)
    idealx.shape = (len(idealx),1) 
    idealy = asarray(idealy)
    idealy.shape = (len(idealy),1) 
    data = np.hstack((idealx,idealy))
    example.writerows(data)
      
    traj.start()
    traj.wait(200.0)


    print("Exiting - Joint Trajectory Action Test Complete")

if __name__ == "__main__":
    main()
