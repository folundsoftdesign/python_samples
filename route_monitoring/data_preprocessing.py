import json
import warnings
from datetime import datetime, timedelta

import folium as fl
import geopandas as gpd
import h3
import hvplot.pandas
import matplotlib.pyplot as plt
import movingpandas as mpd
import numpy as np
import pandas as pd
import shapely as shp
from bson import json_util
from geopandas import GeoDataFrame, read_file
from holoviews import opts
from movingpandas import TrajectoryCollection
from shapely.geometry import LineString, Point, Polygon, shape

# ruff: noqa

print("IMPORTS DONE")
# Load JSON array from file
# with open("synchappgateway.positions.json", "r") as f:
#    data = json.load(f, object_hook=json_util.object_hook)
#
# Convert to DataFrame
# df = pd.DataFrame(data)

print("DATAFRAME DONE")
# json_flat = pd.json_normalize(df["details"])
# df_flat = pd.concat([df.drop(columns=["details"]), json_flat], axis=1)
# df1 = df_flat[(df_flat["latitude"] > 0) & (df_flat["longitude"] > 0)].copy()

# Creating geometry column and setting index
# df1["geometry"] = df1["location"].apply(shape)
# df1.set_index("recordedAt", inplace=True)

# cols_to_keep = [
#    "_id",
#    "clientTime",
#    "deviceId",
#    "event",
#    "latitude",
#    "longitude",
#    "accuracy",
#    "registrationId",
#    "heading",
#    "speed",
#    "altitude",
#    "timestamp",
#    "is_moving",
#    "age",
#    "odometer",
#    "battery.is_charging",
#    "extras.tourId",
#    "extras.forward.extraPayload.vehicle",
#    "extras.forward.extraPayload.dstLatitude",
#    "extras.forward.extraPayload.vehicleState",
#    "extras.forward.extraPayload.dstLongitude",
#    "extras.forward.extraPayload.taskReference",
#    "extras.forward.startedAt",
#    "extras.logoutTime",
#    "geometry",
# ]
#
#
##df1 = df1[cols_to_keep]
# print("COLUMNS DONE")
#
#
# def assign_trajectory_ids(group):
#    traj_id = None
#    current_id = 0
#    route_ended = False
#    ids = []
#
#    for _, row in group.iterrows():
#        traj_id = f"{row['deviceId']}_{current_id}"
#
#        if row["event"] == "reg_started":
#            if route_ended:
#                traj_id = f"{row['deviceId']}_{current_id}"
#                ids.append(traj_id)
#            else:
#                current_id += 1
#                traj_id = f"{row['deviceId']}_{current_id}"
#                ids.append(traj_id)
#
#        elif row["event"] in ["reg_complete", "reg_postpone"]:
#            ids.append(traj_id)
#            current_id += 1  # End the trajectory
#            route_ended = True
#            continue
#        else:
#            ids.append(traj_id)
#            route_ended = False
#    return pd.Series(ids, index=group.index)
#
#
# print("TRAJ ID DONE")
#
## Assigning trajectory ID's
# df1 = df1.sort_values(["deviceId", "recordedAt"], ascending=[True, True])
# df1["odometer"] = df1["odometer"].replace(0, np.nan)
# df1["trajectory_id"] = df1.groupby("deviceId", group_keys=False).apply(assign_trajectory_ids)
#
# print("TRAJ_ID DONE 2")
#
## Creating geodataframe using general crs for Sweden # 3006? # 4619
# gdf = GeoDataFrame(df1, geometry="geometry", crs=4326)
# print("GEO DATAFRAME DONE")


####################################### SAMPLE DATAFRAME TEST #######################################

gdf = gpd.read_parquet("gdf_sample.parquet")

print("SAMPLE GDF LAODED")
print(f"PRINTING % ROWS OF SAMPLE DATA:{gdf.head(5)}")
######################################## CONTINUING  ################################################


# Creating a trajectory collection
tc = mpd.TrajectoryCollection(gdf, "trajectory_id", obj_id_col="deviceId", t="recordedAt")

print("TRAJECTORY COLLECTION DONE")
# Using "recordedAt" as index
# RecordedAt is more correct than deviceTime which is when the device comes back online (confirm)


################################################ FILTERING ############################################################
# When spltting single points aer discarded.
# That is why we have subscripts that says ALEWIL-11_33_5_0,ALEWIL-11_33_5_4, ALEWIL-11_33_5_8
# This means that it was split into 8 segments but a point is not considered a trajector thus they are discarded by the algortihm.

# So first step removes points with +12 hours on both sides and second step removes with one minute on both sides.
split_12_hours = mpd.ObservationGapSplitter(tc).split(gap=timedelta(hours=12))
print("SPLIT 12 HOURS DONE")
split_1_minute = mpd.ObservationGapSplitter(split_12_hours).split(gap=timedelta(minutes=1))
print("SPLIT 1 MINUTE DONE")


########################################################################################################################


###################################################  CREATING CITY POLYGON SECIFYING POPULATION DENSITY ################################################

# sweden_localities = gpd.read_file("Tatorter_2023.gpkg")
# sweden_localities["bef/ha"] = sweden_localities["bef"] / sweden_localities["area_ha"]
# cities = sweden_localities[sweden_localities["bef/ha"] > 0].copy()
# print(cities.crs)  # Original format is swedish 3006 used for topography in sweden.
## Setting swedish cities to general gps format in degrees espg:4326
# cities = cities.to_crs("EPSG:4326")
#
## Combining cities to a single polygon
# combined_polygon = cities.geometry.union_all()
#
## Put the single geometry into a GeoDataFrame while using the correctly adjusted crs from cities.
# combined_gdf = gpd.GeoDataFrame(geometry=[combined_polygon], crs=cities.crs)
#
## Save as GeoPackage (keeps CRS info etc.)
# combined_gdf.to_file("combined_polygon.gpkg", driver="GPKG")

###################################################  LOADING PRECALCULATED CITY POLYGON ################################################

# Read it back
polygon = gpd.read_file("combined_polygon.gpkg")
combined_polygon = polygon.geometry.iloc[0]
print("POLYGON LOADED")


################################################### CREATING BOOLEAN COLUMN "within_city_area" for each point in a trajectory ######################################


for traj in split_1_minute.trajectories:
    # Check if each point is within the polygon, using mask for debugging purposes might set directly on df.
    within_mask = traj.df.geometry.within(combined_polygon)

    # Store the result as a new column
    traj.df["within_city_area"] = within_mask.values

print("WITHIN CITY AREA COMPLETE")

################################################ USING MOVINGPANDAS TO CALCULATE SPEED AND ACCELERATION #################################################

# From documentation (https://movingpandas.readthedocs.io/en/main/api/api/movingpandas.TrajectoryCollection.add_acceleration.html):
# Acceleration is calculated as CRS units per second squared, except if the CRS is geographic (e.g. EPSG:4326 WGS84)
# then acceleration is calculated in meters per second squared."

# We keep data in 4326 hence the unit is m/s^2:
split_1_minute = split_1_minute.add_acceleration(overwrite=True, name="acceleration")

# We calculate speed in m/s and store as column "speed(m/s)":
split_1_minute = split_1_minute.add_speed(overwrite=True, name="speed(m/s)", units=("m", "s"))

# "speed(km/h)" is tored as well since the user will find it easier to comprehend visually:
split_1_minute = split_1_minute.add_speed(overwrite=True, name="speed(km/h)", units=("km", "h"))

# This implementation is for practical purposes. If/when we create our own Pydantic class, we might skip theese.

print("DISTANCE CALC COMPLETE")

#################################################### Calculating speed profiles ####################################################################

# We consider unreasonable speed changes erroneous.
# Preliminary source of attainable speed changes for different car types is chatgpt.

#### Maximum attainable Acceleration values for different car types ####

# Everyday cars: 2–4 m/s²
# High-performance cars: 6–12 m/s²
# F1/race cars: 12–20 m/s²

#### Braking / deceleration ####

# Typical street cars: ~6–8 m/s² max braking on dry asphalt.
# Race cars: up to 15–20 m/s².


# Our limit is set at 10m/s^2 ie a speed increase or decrease of 10m/s every second. Consider adjusting these.
# Limits are set conservatively.
# We are looking at 10 sec. intervals (negative effect on acc dec estimates) and heavy trucks (negative effect on both acc and dec).

#### REGULAR SPEED PROFILE ####
for traj in split_1_minute:
    # Abrubt speed change
    traj.df["abrubt_speed_change"] = (abs(traj.df["acceleration"]) > 1) & (abs(traj.df["acceleration"]) < 10)
    traj.df["abrubt_speed_change_count"] = traj.df["abrubt_speed_change"].sum()

    # Regular speed change
    traj.df["regular_speed_change"] = abs(traj.df["acceleration"]) < 1
    traj.df["regular_speed_change_count"] = traj.df["regular_speed_change"].sum()

    # Erroneous speed change
    traj.df["error_speed_change"] = abs(traj.df["acceleration"]) >= 10
    traj.df["error_speed_change_count"] = traj.df["error_speed_change"].sum()

    # General speed change profile
    traj.df["speed_change_profile"] = traj.df["abrubt_speed_change_count"] / (
        traj.df["regular_speed_change_count"] + traj.df["abrubt_speed_change_count"]
    )
    # FOr debugging
    traj.df["speed_change_profile_replace"] = traj.df["abrubt_speed_change_count"].replace(0, np.nan) / (
        traj.df["regular_speed_change_count"] + traj.df["abrubt_speed_change_count"]
    )

print("COMPLETED SPEED PROFILES GENERAL")


#### CITY SPEED PROFILE ####
for traj in split_1_minute:
    # Abrubt speed change in the city
    traj.df["abrubt_speed_change_city"] = (
        (abs(traj.df["acceleration"]) > 1) & (abs(traj.df["acceleration"]) < 10) & (traj.df["within_city_area"] == True)
    )
    traj.df["abrubt_speed_change_city_count"] = traj.df["abrubt_speed_change_city"].sum()

    # Regular speed changes in the city
    traj.df["regular_speed_change_city"] = (abs(traj.df["acceleration"]) < 1) & (traj.df["within_city_area"] == True)
    traj.df["regular_speed_change_city_count"] = traj.df["regular_speed_change_city"].sum()

    # Erroneous speed reading in the city
    traj.df["error_speed_change_city"] = (abs(traj.df["acceleration"]) >= 10) & (traj.df["within_city_area"] == True)
    traj.df["error_speed_change_city_count"] = traj.df["error_speed_change_city"].sum()

    ## SPEED CHANGE PROFILE CITY
    traj.df["speed_change_profile_city"] = traj.df["abrubt_speed_change_city_count"] / (
        traj.df["regular_speed_change_city_count"] + traj.df["abrubt_speed_change_city_count"]
    )
    ## For debuggin
    traj.df["speed_change_profile_city_replace"] = traj.df["abrubt_speed_change_city_count"].replace(0, np.nan) / (
        traj.df["regular_speed_change_city_count"] + traj.df["abrubt_speed_change_city_count"]
    )

print("COMPLETED SPEED PROFILES CITY")

####  NOT CITY SPEED PROFILE  ####
for traj in split_1_minute:
    # Abrubt speed change not in the city
    traj.df["abrubt_speed_change_not_city"] = (
        (abs(traj.df["acceleration"]) > 1) & (abs(traj.df["acceleration"]) < 10) & (traj.df["within_city_area"] == False)
    )
    traj.df["abrubt_speed_change_not_city_count"] = traj.df["abrubt_speed_change_not_city"].sum()

    # Regular speed change not in the city
    traj.df["regular_speed_change_not_city"] = (abs(traj.df["acceleration"]) < 1) & (traj.df["within_city_area"] == False)
    traj.df["regular_speed_change_not_city_count"] = traj.df["regular_speed_change_not_city"].sum()

    # Erroneous speed change not in the city
    traj.df["error_speed_change_not_city"] = (abs(traj.df["acceleration"]) >= 10) & (traj.df["within_city_area"] == False)
    traj.df["error_speed_change_not_city_count"] = traj.df["error_speed_change_not_city"].sum()

    # Speed profile not in the city
    traj.df["speed_change_profile_not_city"] = traj.df["abrubt_speed_change_not_city_count"] / (
        traj.df["regular_speed_change_not_city_count"] + traj.df["abrubt_speed_change_not_city_count"]
    )
    # For debuggin
    traj.df["speed_change_profile_not_city_replace"] = traj.df["abrubt_speed_change_not_city_count"].replace(0, np.nan) / (
        traj.df["regular_speed_change_not_city_count"] + traj.df["abrubt_speed_change_not_city_count"]
    )

print("COMPLETED SPEED PROFILES NOT CITY")

################################################# ODOMETER LENGTHS ####################################################
point_gdf = split_1_minute.to_point_gdf()

# assigning odometer distance to trajectories
point_gdf["odometer_length"] = point_gdf.groupby("trajectory_id")["odometer"].transform(lambda x: x.max() - x.min())
point_gdf["odometer_delta"] = point_gdf.groupby("trajectory_id")["odometer"].diff()


###############################################  DEBUGGING point_gdf ######################################################
print(point_gdf["within_city_area"].value_counts())


################################################### CREATING TRAJ_DF ############################################################

# Using moving pandas frameworj hence PointGeoDataframe -> TrajectoryCollection -> TrajectoryDataframe
traj_c = mpd.TrajectoryCollection(point_gdf, "trajectory_id", obj_id_col="deviceId", t="recordedAt")

# In all cases but "acceleration", values are constant thus "max" is one of many functions that would retrieve the same value(min, mean, etc)
traj_gdf_final = traj_c.to_traj_gdf(
    agg={
        "acceleration": ["max", "min"],
        "error_speed_change_count": ["max"],
        "error_speed_change_not_city_count": ["max"],
        "error_speed_change_city_count": ["max"],
        "abrubt_speed_change_count": ["max"],
        "abrubt_speed_change_not_city_count": ["max"],
        "abrubt_speed_change_city_count": ["max"],
        "regular_speed_change_count": ["max"],
        "regular_speed_change_not_city_count": ["max"],
        "regular_speed_change_city_count": ["max"],
        "speed_change_profile": ["max"],
        "speed_change_profile_replace": ["max"],
        "speed_change_profile_not_city": ["max"],
        "speed_change_profile_not_city_replace": ["max"],
        "speed_change_profile_city": ["max"],
        "speed_change_profile_city_replace": ["max"],
        "odometer_length": ["max"],
        "odometer_delta": ["max"],
    }
)
print("TRAJ_GDF_FINAL COMPLETE")

# Since max was used to retrieve data, we rename columns.
traj_gdf_final.rename(
    columns={
        "speed_change_profile_max": "speed_change_profile",
        "speed_change_profile_replace_max": "speed_change_profile_replace",
        "speed_change_profile_not_city_max": "speed_change_profile_not_city",
        "speed_change_profile_not_city_replace_max": "speed_change_profile_not_city_replace",
        "speed_change_profile_city_max": "speed_change_profile_city",
        "speed_change_profile_city_replace_max": "speed_change_profile_city_replace",
        "error_speed_change_count_max": "error_speed_change_count",
        "error_speed_change_not_city_count_max": "error_speed_change_not_city_count",
        "error_speed_change_city_count_max": "error_speed_change_city_count",
        "abrubt_speed_change_count_max": "abrubt_speed_change_count",
        "abrubt_speed_change_not_city_count_max": "abrubt_speed_change_not_city_count",
        "abrubt_speed_change_city_count_max": "abrubt_speed_change_city_count",
        "regular_speed_change_count_max": "regular_speed_change_count",
        "regular_speed_change_not_city_count_max": "regular_speed_change_not_city_count",
        "regular_speed_change_city_count_max": "regular_speed_change_city_count",
        "odometer_length_max": "odometer_length",
    },
    inplace=True,
)

print("COLUMNS RENAMED")


######################################## CALCULATING DIFFERENCE BETWEEN CALCULATED LENGTH AND ODOMETER READINGS  ###################################

# Here we calculate the difference between the distance we get from reading the odometer at start and end of a trajectory,
# with the distance we get from the coordinates.
traj_gdf_final["distance_diff"] = round(traj_gdf_final["odometer_length"] - traj_gdf_final["length"], 1)

#  The distance difference in percent of the length we measure form coordinates.
traj_gdf_final["distance_diff_pct"] = round(traj_gdf_final["distance_diff"] / traj_gdf_final["length"] * 100, 1)

# The distance difference in percent as an absolute number.
# Allows filtering on deviations without taking into account whether odometer distance is bigger or smaller than the measured distance.
traj_gdf_final["distance_diff_pct_abs"] = abs(round(traj_gdf_final["distance_diff"] / traj_gdf_final["length"] * 100, 1))


########################################## Creating columns that allows filtering on mother trajectories. ##########################################

# "split_delta_t_12hrs" yields the mother trajectory that was split into children based on a delta_t_12hrs criteria.

# "split_delta_t_1min" is a child of the ID in "split_delta_t_12hrs" above,
# and the mother of child trajectories that where split based on a delta_t_1min criteria.


# Naming using split based on "_" is vulnerable to device names containing "_".
# Not a problem in case of SOS but keep in mind.
# NB the values are only used for visual inspection and errors will be obvious.

traj_gdf_final["deviceId"] = traj_gdf_final["trajectory_id"].str.split("_", n=1).str[0]
traj_gdf_final["split_delta_t_12hrs"] = traj_gdf_final["trajectory_id"].str.split("_").str[1].astype(int)
traj_gdf_final["split_delta_t_1min"] = traj_gdf_final["trajectory_id"].str.split("_").str[2].astype(int)

# Ordering columns for better userexperience while filtering in streamlit.
first_cols = ["trajectory_id", "deviceId", "split_delta_t_12hrs", "split_delta_t_1min"]
cols_order = first_cols + [col for col in traj_gdf_final.columns if col not in first_cols]
traj_gdf_final = traj_gdf_final[cols_order]
