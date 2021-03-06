## Project: Perception Pick & Place

### Writeup / README

#### 1. Provide a Writeup / README that includes all the rubric points and how you addressed each one.  You can submit your writeup as markdown or pdf.  

You're reading it!

### Exercise 1, 2 and 3 pipeline implemented
#### 1. Complete Exercise 1 steps. Pipeline for filtering and RANSAC plane fitting implemented.

* Statistical Outlier Filtering the number of neighboring points 6 and threshold set as 0.1, any points with mean distance larger than (mean distance+x \* std_dev) will be considered as outlier.
```
    outlier_filter = plc.make_statistical_outlier_filter()
    # Set the number of neighboring points to analyze for any given point
    outlier_filter.set_mean_k(6)
    # Set threshold scale factor
    x = 1
    # Any point with a mean distance larger than global (mean distance+x*std_dev) will be considered outlier
    outlier_filter.set_std_dev_mul_thresh(x)
    # Finally call the filter function for magic
    cloud_filtered = outlier_filter.filter()
```
* Downsampling voxel grid with LEAF_SIZE = 0.005
```
    # Create a VoxelGrid filter object for our filtered point cloud
    vox = cloud_filtered.make_voxel_grid_filter()
    # Choose a voxel (also known as leaf) size
    LEAF_SIZE = 0.005
    # Set the voxel (or leaf) size  
    vox.set_leaf_size(LEAF_SIZE, LEAF_SIZE, LEAF_SIZE)
    # Call the filter function to obtain the resultant downsampled point cloud
    cloud_filtered = vox.filter()
```
* PassThrough Filter for y and z axes
```
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
    
    cloud_filtered = passthrough.filter()
```
* Finnaly RANSAC Plane Segmentation
```
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
    
    # Extract inliers
    cloud_filtered = cloud_filtered.extract(inliers, negative=True)

    # There are still a lot of noice, let's try to remove it once again with k-means
    # we start by creating a filter object: 
    outlier_filter = cloud_filtered.make_statistical_outlier_filter()
    # Set the number of neighboring points to analyze for any given point
    outlier_filter.set_mean_k(60)
    # Set threshold scale factor
    x = 1
    # Any point with a mean distance larger than global (mean distance+x*std_dev) will be considered outlier
    outlier_filter.set_std_dev_mul_thresh(x)
    # Finally call the filter function for magic
    cloud_filtered = outlier_filter.filter()
```
#### 2. Complete Exercise 2 steps: Pipeline including clustering for segmentation implemented.
```
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
```

#### 2. Complete Exercise 3 Steps.  Features extracted and SVM trained.  Object recognition implemented.
* Extract features
```
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

```
* Train SVM

I took 1000 samples of each object.
Here is SVM setup:
```
    clf = svm.SVC(kernel='linear', tol=1e-4)
```
Here is confusion matrix. It is not perfect, but hopfully it will do the trick
![CM](CM.png)

Eventially it didn't do the trcik. So it turns out that I was building histogram for normals only with positive values range=(0,255) so I change it to [-100,100] and it worked even with 50 samples of each object.

![CM2](CM2.png)

### Pick and Place Setup

#### 1. For all three tabletop setups (`test*.world`), perform object recognition, then read in respective pick list (`pick_list_*.yaml`). Next construct the messages that would comprise a valid `PickPlace` request output them to `.yaml` format.

Here is what I got as a result:
![CM2](o1.png)
![CM2](o22.png)
![CM2](o3.png)

All yaml files are in the output directory


###Spend some time at the end to discuss your code, what techniques you used, what worked and why, where the implementation might fail and how you might improve it if you were going to pursue this project further.

It seems that SVM still can be better trained. I need to spend some more time playing with parameters and features.



