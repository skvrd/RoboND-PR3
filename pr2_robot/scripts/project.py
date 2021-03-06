#!/usr/bin/env python

# Import modules
import numpy as np
import sklearn
from sklearn.preprocessing import LabelEncoder
import pickle
from sensor_stick.srv import GetNormals
from sensor_stick.features import compute_color_histograms
from sensor_stick.features import compute_normal_histograms
from visualization_msgs.msg import Marker
from sensor_stick.marker_tools import *
from sensor_stick.msg import DetectedObjectsArray
from sensor_stick.msg import DetectedObject
from pcl_helper import *

import rospy
import tf
from geometry_msgs.msg import Pose
from std_msgs.msg import Float64
from std_msgs.msg import Int32
from std_msgs.msg import String
from pr2_robot.srv import *
from rospy_message_converter import message_converter
import yaml


# Helper function to get surface normals
def get_normals(cloud):
    get_normals_prox = rospy.ServiceProxy('/feature_extractor/get_normals', GetNormals)
    return get_normals_prox(cloud).cluster

# Helper function to create a yaml friendly dictionary from ROS messages
def make_yaml_dict(test_scene_num, arm_name, object_name, pick_pose, place_pose):
    yaml_dict = {}
    yaml_dict["test_scene_num"] = test_scene_num.data
    yaml_dict["arm_name"]  = arm_name.data
    yaml_dict["object_name"] = object_name.data
    yaml_dict["pick_pose"] = message_converter.convert_ros_message_to_dictionary(pick_pose)
    yaml_dict["place_pose"] = message_converter.convert_ros_message_to_dictionary(place_pose)
    return yaml_dict

# Helper function to output to yaml file
def send_to_yaml(yaml_filename, dict_list):
    data_dict = {"object_list": dict_list}
    with open(yaml_filename, 'w') as outfile:
        yaml.dump(data_dict, outfile, default_flow_style=False)

# Callback function for your Point Cloud Subscriber
def pcl_callback(pcl_msg):

# Exercise-2 TODOs:
    
    # TODO: Convert ROS msg to PCL data
    plc = ros_to_pcl(pcl_msg)

    # TODO: Statistical Outlier Filtering\
    # we start by creating a filter object: 
    outlier_filter = plc.make_statistical_outlier_filter()
    # Set the number of neighboring points to analyze for any given point
    outlier_filter.set_mean_k(6)
    # Set threshold scale factor
    x = 1
    # Any point with a mean distance larger than global (mean distance+x*std_dev) will be considered outlier
    outlier_filter.set_std_dev_mul_thresh(x)
    # Finally call the filter function for magic
    cloud_filtered = outlier_filter.filter()

    # TODO: Voxel Grid Downsampling
    # Create a VoxelGrid filter object for our filtered point cloud
    vox = cloud_filtered.make_voxel_grid_filter()
    # Choose a voxel (also known as leaf) size
    LEAF_SIZE = 0.005
    # Set the voxel (or leaf) size  
    vox.set_leaf_size(LEAF_SIZE, LEAF_SIZE, LEAF_SIZE)
    # Call the filter function to obtain the resultant downsampled point cloud
    cloud_filtered = vox.filter()

    # TODO: PassThrough Filter
    # Create a PassThrough filter object.
    passthrough = cloud_filtered.make_passthrough_filter()
    # Assign axis and range to the passthrough filter object.
    filter_axis = 'z'
    passthrough.set_filter_field_name(filter_axis)
    # Since robot is looking from top to bottom
    # So removing only small part under the table should be ok
    # As well as removing around the same amount from the top
    axis_min = 0.60
    axis_max = 1.40
    passthrough.set_filter_limits (axis_min, axis_max)
    passthrough = passthrough.filter()    

    passthrough = passthrough.make_passthrough_filter()

    # We also want to get rid of boxes
    filter_axis = 'y'
    passthrough.set_filter_field_name(filter_axis)
    axis_min = -0.5
    axis_max = 0.5
    passthrough.set_filter_limits(axis_min, axis_max)
    # Finally use the filter function to obtain the resultant point cloud.
    cloud_filtered = passthrough.filter()


    # TODO: RANSAC Plane Segmentation
    # Create the segmentation object
    seg = cloud_filtered.make_segmenter()

    # Set the model you wish to fit 
    seg.set_model_type(pcl.SACMODEL_PLANE)
    seg.set_method_type(pcl.SAC_RANSAC)

    # Max distance for a point to be considered fitting the model
    # Experiment with different values for max_distance 
    # for segmenting the table
    max_distance = 0.01
    seg.set_distance_threshold(max_distance)

    # Call the segment function to obtain set of inlier indices and model coefficients
    inliers, coefficients = seg.segment()

    # TODO: Extract inliers and outliers
    cloud_filtered = cloud_filtered.extract(inliers, negative=True)

    # TODO: Euclidean Clustering

    white_cloud = XYZRGB_to_XYZ(cloud_filtered)# Apply function to convert XYZRGB to XYZ
    tree = white_cloud.make_kdtree()

    # Create a cluster extraction object
    ec = white_cloud.make_EuclideanClusterExtraction()
    # Set tolerances for distance threshold 
    # as well as minimum and maximum cluster size (in points)

    ec.set_ClusterTolerance(0.01)
    ec.set_MinClusterSize(60)
    ec.set_MaxClusterSize(6000)
    # Search the k-d tree for clusters
    ec.set_SearchMethod(tree)
    # Extract indices for each of the discovered clusters
    cluster_indices = ec.Extract()

    # TODO: Create Cluster-Mask Point Cloud to visualize each cluster separately
    #Assign a color corresponding to each segmented object in scene
    cluster_color = get_color_list(len(cluster_indices))

    color_cluster_point_list = []

    for j, indices in enumerate(cluster_indices):
        for i, indice in enumerate(indices):
             color_cluster_point_list.append([white_cloud[indice][0],
                                        white_cloud[indice][1],
                                        white_cloud[indice][2],
                                         rgb_to_float(cluster_color[j])])    
    #Create new cloud containing all clusters, each with unique color
    cluster_cloud = pcl.PointCloud_PointXYZRGB()
    cluster_cloud.from_list(color_cluster_point_list)

    # TODO: Convert PCL data to ROS messages
    cloud_filtered_msg = pcl_to_ros(cluster_cloud)
    # TODO: Publish ROS messages
    pcl_objects_pub.publish(cloud_filtered_msg)

# Exercise-3 TODOs:

    # Classify the clusters! (loop through each detected cluster one at a time)
    detected_objects_labels = []
    detected_objects = []
    for index, pts_list in enumerate(cluster_indices):
        # Grab the points for the cluster
        pcl_cluster = cloud_filtered.extract(pts_list)
        ros_cluster = pcl_to_ros(pcl_cluster)    
        # Compute the associated feature vector
        color_hists = compute_color_histograms(ros_cluster, using_hsv=True)
        normals = get_normals(ros_cluster)
        normal_hists = compute_normal_histograms(normals)
        features = np.concatenate((color_hists, normal_hists))
        # Make the prediction
        prediction = clf.predict(scaler.transform(features.reshape(1,-1)))
        label = encoder.inverse_transform(prediction)[0]
        detected_objects_labels.append(label)
        # Publish a label into RViz
        label_pos = list(white_cloud[pts_list[0]])
        label_pos[2] += .22
        
        object_markers_pub.publish(make_label(label,label_pos, index))

        # Add the detected object to the list of detected objects.
        do = DetectedObject()
        do.label = label
        do.cloud = ros_cluster
        detected_objects.append(do)       
    

    # Suggested location for where to invoke your pr2_mover() function within pcl_callback()
    # Could add some logic to determine whether or not your object detections are robust
    # before calling pr2_mover()
    try:
        pr2_mover(detected_objects)
    except rospy.ROSInterruptException:
        pass

# function to load parameters and request PickPlace service
def pr2_mover(object_list):

    # TODO: Initialize variables
    test_scene_num = Int32()
    arm_name = String()
    object_name = String()
    pick_pose = Pose()
    place_pose = Pose()
    dict_list = []
    labels = []
    centroids = []
    # TODO: Get/Read parameters

    # TODO: Rotate PR2 in place to capture side tables for the collision map
    # TODO: Parse parameters into individual variables
    object_list_param = rospy.get_param('/object_list')


    for object in object_list:
        labels.append(object.label)

        points_arr = ros_to_pcl(object.cloud).to_array()

        pick_from = np.mean(points_arr, axis=0)[:3]
        pick_pose.position.x = np.float(pick_from[0])
        pick_pose.position.y = np.float(pick_from[1])
        pick_pose.position.z = np.float(pick_from[2])

        test_scene_num.data = 3  
        object_name.data = str(object.label)
        
        
        which_arm = String()        
        place_pose = Pose()

        # TODO: Loop through the pick list
        for i in range(len(object_list)):  
             pick_object_name = object_list_param[i]['name']
             object_group = object_list_param[i]['group']
             # TODO: Get the PointCloud for a given object and obtain it's centroid
             if pick_object_name == object.label:
                 if object_group == 'green':
                     arm_name.data ='right'
                     place_pose.position.x = 0.
                     place_pose.position.y = -0.71
                     place_pose.position.z = 0.605
                 else:
                     arm_name.data ='left'
                     place_pose.position.x = 0.
                     place_pose.position.y = 0.71
                     place_pose.position.z = 0.605
                 break
        # TODO: Create 'place_pose' for the object
        yaml_dict = make_yaml_dict(test_scene_num, arm_name, object_name, pick_pose, place_pose)
        dict_list.append(yaml_dict)
        # TODO: Assign the arm to be used for pick_place

        # TODO: Create a list of dictionaries (made with make_yaml_dict()) for later output to yaml format

        # Wait for 'pick_place_routine' service to come up
        #rospy.wait_for_service('pick_place_routine')

        #try:
        #    pick_place_routine = rospy.ServiceProxy('pick_place_routine', PickPlace)

            # TODO: Insert your message variables to be sent as a service request
#            resp = pick_place_routine(test_scene_num, object_name, arm_name, pick_pose, place_pose)
#
#            print ("Response: ",resp.success)
#
#        except rospy.ServiceException, e:
#            print "Service call failed: %s"%e

    # TODO: Output your request parameters into output yaml file
    yaml_name = 'output_'+str(test_scene_num.data)+'.yaml'
    send_to_yaml(yaml_name, dict_list)
    print(yaml_name + "has been saved.")

if __name__ == '__main__':

    # TODO: ROS node initialization
    rospy.init_node('project', anonymous=True)
    # TODO: Create Subscribers
    pcl_sub = rospy.Subscriber("/pr2/world/points", pc2.PointCloud2, pcl_callback, queue_size=1)
    # TODO: Create Publishers
    object_markers_pub = rospy.Publisher("/object_markers",Marker,queue_size =10)
    pcl_objects_pub = rospy.Publisher("/pcl_objects", PointCloud2, queue_size=1)
    # TODO: Load Model From disk
    model = pickle.load(open('model_1000.sav', 'rb'))
    clf = model['classifier']
    encoder = LabelEncoder()
    encoder.classes_ = model['classes']
    scaler = model['scaler']
    # Initialize color_list
    get_color_list.color_list = []

    # TODO: Spin while node is not shutdown
    while not rospy.is_shutdown():
       rospy.spin()
