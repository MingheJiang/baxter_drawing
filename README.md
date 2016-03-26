## Project - Baxter Take photo and Draw

#### Minghe Jiang



### Introduction:


* #### This purpose of this project was to create a demonstration that combined robot arm kinematics and control with basic image processing. In the demo, a user draws a picture on a whiteboard and we use the right hand camera of a Baxter Research Robot to take an image of the user's picture. Canny edge detection is used to build a set of SE(3) waypoints that represent the user's picture. Finally, we solve the inverse kinematics for each waypoint, and design a joint space trajectory for Baxter's left arm to follow. Baxter then draws a replica of the user's original picture



### Files In Package:
* #### In Package (drawing_left):
	
	>####takephoto_right.py
	
	>>This file firstly let the right camera find the content in the paper. Then after taking picture of the content and appling image processing on it, its pixels converted into x,y locations in Baxter workspace finally.
	
	>####setup.dat:
	>>Setup right arm and distance.
	
* #### In Package (drawing_left):

	>####joint_trajectory_action_server.py
	
	>####joint_trajectory_client.py:
	
	>>This file reads x,y,z data from the csv file which exported from takephoto_right.py and converts these locations into baxter 7 joint angles by using `baxter_ik_move()`. Then these sets of 7 joint angles are put into joint trajectory one by one. The trajectory is a function of time. Baxter will follow this trajectory to draw the content of picture. 
	
	>####setup.dat:
	>>Setup left arm and distance.

### Image Processing:

The right camera firstly gets the canny image of its vision by `cv2.Canny()` and then finds the location of the content in paper by finding and moving to the x,y location of the center of its contour rectangle several times with `cv2.findContours()` and `cv2.rectangle()`.

After finding the content and taking the canny image of it, the image is dilated and eroded in order to get the better result for houghing lines. By implementing `cv2.HoughLinesP()`, the sets of x,y pixels of these lines is obtained. 

The function `pixel_to_baxter_left()` converts these x,y pixels into Baxter's left hand workspace.

Since the x,y locations we obtained from last step is out-of-order, they were reordered in a consequence that the next point is always nearest the former one.

Then the new x,y locations are splined by the function  `interpolate.splev()` to get much smoother lines. 

### Challenge:
The difficult part would be get a better image processing result and let joint trajectory action client works well every time. Since the image processing is not works ideally every time, sometimes it just gets a worse contour of edge. Sometimes the values for image processing functions are needed to be modified for specific shapes.

### Future Work:
The finding content of paper part is not very ideal, in order to improve it, the camera could be set to be able to recoginze the red color(assume we let people to draw with red pen) and then find it. 

The image processing part is not works well every time, so the values of some functions like canny and houghLinesP should be modified to be worked with more shapes. 

The drawing result cannot be oriented now, so later the orientation of the image could be added.
