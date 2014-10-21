'''
# All the functions for the MCC search algorithm
# Following RCMES dataformat in format (t,lat,lon), value
'''

import datetime
from datetime import timedelta, datetime
import calendar
import fileinput
import glob
import itertools
import json
import math
import Nio
from netCDF4 import Dataset, num2date, date2num
import numpy as np
import numpy.ma as ma
import os
import pickle
import re
from scipy import ndimage
from scipy.interpolate import griddata
import string
import subprocess
#from subprocess import Popen, PIPE
import sys
import time

import networkx as nx

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.dates import DateFormatter,HourLocator 
from matplotlib import cm
import matplotlib.cm as cm
import matplotlib.colors as mcolors
from matplotlib.ticker import FuncFormatter, FormatStrFormatter
from matplotlib import path
from matplotlib.mlab import griddata
from mpl_toolkits.basemap import Basemap

#existing modules in services
#import files
import process
#----------------------- GLOBAL VARIABLES --------------------------
# --------------------- User defined variables ---------------------
#FYI the lat lon values are not necessarily inclusive of the points given. These are the limits
#the first point closest the the value (for the min) from the MERG data is used, etc.
LATMIN = '5.0' #'-60.0'#  #4.0' #'5.0' #min latitude; -ve values in the SH e.g. 5S = -5
LATMAX = '19.0' #'60.0' # #'13.0' #'19.0' #max latitude; -ve values in the SH e.g. 5S = -5 20.0
LONMIN = '-5.0' #'-180.0' # #'-6.0' #'-5.0' #min longitude; -ve values in the WH e.g. 59.8W = -59.8 -30
LONMAX = '9.0' #'120.0' # #'13.0' #'9.0' #min longitude; -ve values in the WH e.g. 59.8W = -59.8  30
XRES = 4.0				#x direction spatial resolution in km
YRES = 4.0				#y direction spatial resolution in km
TRES = 1 				#temporal resolution in hrs
LAT_DISTANCE = 111.0 	#the avg distance in km for 1deg lat for the region being considered 
LON_DISTANCE = 111.0    #the avg distance in km for 1deg lon for the region being considered
STRUCTURING_ELEMENT = [[0,1,0],[1,1,1],[0,1,0]] #the matrix for determining the pattern for the contiguous boxes and must
    											#have same rank of the matrix it is being compared against 
#criteria for determining cloud elements and edges
T_BB_MAX = 243  #warmest temp to allow (-30C to -55C according to Morel and Sensi 2002)
T_BB_MIN = 218  #cooler temp for the center of the system
CONVECTIVE_FRACTION = 0.90 #the min temp/max temp that would be expected in a CE.. this is highly conservative (only a 10K difference)
MIN_MCS_DURATION = 3    #minimum time for a MCS to exist
AREA_MIN = 2400.0		#minimum area for CE criteria in km^2 according to Vila et al. (2008) is 2400
MIN_OVERLAP= 10000.00   #km^2  from Williams and Houze 1987, indir ref in Arnaud et al 1992

#---the MCC criteria
ECCENTRICITY_THRESHOLD_MAX = 1.0  #tending to 1 is a circle e.g. hurricane, 
ECCENTRICITY_THRESHOLD_MIN = 0.50 #tending to 0 is a linear e.g. squall line
OUTER_CLOUD_SHIELD_AREA = 80000.0 #km^2
INNER_CLOUD_SHIELD_AREA = 30000.0 #km^2
OUTER_CLOUD_SHIELD_TEMPERATURE = 233 #in K
INNER_CLOUD_SHIELD_TEMPERATURE = 213 #in K
MINIMUM_DURATION = 6 #min number of frames the MCC must exist for (assuming hrly frames, MCCs is 6hrs)
MAXIMUM_DURATION = 24#max number of framce the MCC can last for 
#------------------- End user defined Variables -------------------
edgeWeight = [1,2,3] #weights for the graph edges
#graph object fo the CEs meeting the criteria
CLOUD_ELEMENT_GRAPH = nx.DiGraph()
#graph meeting the CC criteria
PRUNED_GRAPH = nx.DiGraph()
#------------------------ End GLOBAL VARS -------------------------
#************************ Begin Functions *************************
#******************************************************************
def readMergData(dirname, filelist=None):
	'''
	Purpose::
	    Read MERG data into RCMES format
	
	Input::
	    dirname: a string representing the directory to the MERG files in NETCDF format
	    filelist (optional): a list of strings representing the filenames betweent the start and end dates provided
	
	Output::
	    A 3D masked array (t,lat,lon) with only the variables which meet the minimum temperature 
	    criteria for each frame

	Assumptions::
	    The MERG data has been converted to NETCDF using LATS4D
	    The data has the same lat/lon format

	TODO:: figure out how to use netCDF4 to do the clipping tmp = netCDF4.Dataset(filelist[0])

	'''

	global LAT
	global LON

	# these strings are specific to the MERG data
	mergVarName = 'ch4'
	mergTimeVarName = 'time'
	mergLatVarName = 'latitude'
	mergLonVarName = 'longitude'
	
	
	if filelist == None:
		filelistInstructions = dirname + '/*'
		filelist = glob.glob(filelistInstructions)

	
	#sat_img is the array that will contain all the masked frames
	mergImgs = []
	#timelist of python time strings
	timelist = [] 
	time2store = None
	tempMaskedValueNp =[]
	

	filelist.sort()
	nfiles = len(filelist)

	# Crash nicely if there are no netcdf files
	if nfiles == 0:
		print 'Error: no files in this directory! Exiting elegantly'
		sys.exit()
	else:
		# Open the first file in the list to read in lats, lons and generate the  grid for comparison
		tmp = Nio.open_file(filelist[0], format='nc')

		#clip the lat/lon grid according to user input
		#http://www.pyngl.ucar.edu/NioExtendedSelection.shtml
		latsraw = tmp.variables[mergLatVarName][mergLatVarName+"|"+LATMIN+":"+LATMAX].astype('f2')
		lonsraw = tmp.variables[mergLonVarName][mergLonVarName+"|"+LONMIN+":"+LONMAX].astype('f2')
		lonsraw[lonsraw > 180] = lonsraw[lonsraw > 180] - 360.  # convert to -180,180 if necessary
		

		# #Using NETCDF instead of Nio
		#mergData = Dataset(filelist[0],'r', format='NETCDF')
		# brightnesstemp = mergData.variables['ch4'][:,:,:]
		# latsraw = mergData.variables['latitude'][:]
		# lonsraw = mergData.variables['longitude'][:]
		
		#lonsraw[lonsraw > 180] = lonsraw[lonsraw > 180] - 360.  # convert to -180,180 if necessary

		
		LON, LAT = np.meshgrid(lonsraw, latsraw)
		
		#clean up
		latsraw =[]
		lonsraw = []
		nygrd = len(LAT[:, 0]); nxgrd = len(LON[0, :])
		tmp.close
		#mergData.close

		# #determine the subsection for future
		# bbox = [LONMIN, LONMAX, LATMIN, LATMAX]
		# iLONMIN, iLONMAX, jLATMIN, jLATMAX = bbox2ij(LON, LAT, bbox)

		#print LAT[:,0]

	for files in filelist:
		
		# #thisFile = Dataset(files,'r', format='NETCDF')

		# #tempRaw = thisFile.variables[mergVarName][:,jLATMIN:jLATMAX, iLONMIN:iLONMAX].astype('int16')
		# #print tempRaw.shape

		# #print "tempRaw ", tempRaw

		# tempMask = ma.masked_array(tempRaw, mask=(tempRaw > T_BB_MAX), fill_value=0) 
		# #print "tempMask ", tempMask
		
		# #get the actual values that the mask returned
		# tempMaskedValue = ma.zeros((tempRaw.shape)).astype('int16')
		# for index, value in maenumerate(tempMask): 
		# 	time_index, lat_index, lon_index = index			
		# 	tempMaskedValue[time_index,lat_index, lon_index]=value	
			
		# timesRaw = thisFile.variables[mergTimeVarName]
		# #convert this time to a python datastring
		# time2store, _ = process.getModelTimes(files, mergTimeVarName)


		#try:
		thisFile = Nio.open_file(files, format='nc') 
		#clip the dataset according to user lat,lon coordinates
		#mask the data and fill with zeros for later 
		tempRaw = thisFile.variables[mergVarName][mergLatVarName+"|"+LATMIN+":"+LATMAX \
		                           +" " +mergLonVarName+"|"+LONMIN+":"+LONMAX ].astype('int16')




		#thisFile = Dataset(files,'r', format='NETCDF')
		
		#tempRaw = thisFile.variables['ch4'][:,:,:]
		# tempRaw = thisFile.variables[mergVarName][mergLatVarName+"|"+LATMIN+":"+LATMAX \
		#                            +" " +mergLonVarName+"|"+LONMIN+":"+LONMAX ].astype('int16')
		

		tempMask = ma.masked_array(tempRaw, mask=(tempRaw > T_BB_MAX), fill_value=0) 
		
		#get the actual values that the mask returned

		tempMaskedValue = ma.zeros((tempRaw.shape)).astype('int16')
		for index, value in maenumerate(tempMask): 
			time_index, lat_index, lon_index = index	
			tempMaskedValue[time_index,lat_index, lon_index]=value	
			
		timesRaw = thisFile.variables[mergTimeVarName]
		#convert this time to a python datastring
		time2store, _ = process.getModelTimes(files, mergTimeVarName)
		#print time2store
		#sys.exit()#extend instead of append because getModelTimes returns a list already and we don't 
		#want a list of list
		timelist.extend(time2store)
		mergImgs.extend(tempMaskedValue) 
		
		thisFile.close
		thisFile = None
		
		# except:
		# 	print "bad file! ", file

	mergImgs = ma.array(mergImgs)

	return mergImgs, timelist
#******************************************************************
def findCloudElements(mergImgs,timelist,TRMMdirName=None):
	'''
	Purpose::
	    Determines the contiguous boxes for a given time of the satellite images i.e. each frame
        using scipy ndimage package
	
	Input::	
		mergImgs: masked numpy array in (time,lat,lon),T_bb representing the satellite data. This is masked based on the
		maximum acceptable temperature, T_BB_MAX
		timelist: a list of python datatimes
		TRMMdirName (optional): string representing the path where to find the TRMM datafiles
		
	Output::
	    CLOUD_ELEMENT_GRAPH: a Networkx directed graph where each node contains the information in cloudElementDict
	    The nodes are determined according to the area of contiguous squares. The nodes are linked through weighted edges.

		cloudElementDict = {'uniqueID': unique tag for this CE, 
							'cloudElementTime': time of the CE,
							'cloudElementLatLon': (lat,lon,value) of MERG data of CE, 
							'cloudElementCenter':list of floating-point [lat,lon] representing the CE's center 
							'cloudElementArea':floating-point representing the area of the CE, 
							'cloudElementEccentricity': floating-point representing the shape of the CE, 
							'cloudElementTmax':integer representing the maximum Tb in CE, 
							'cloudElementTmin': integer representing the minimum Tb in CE, 
							'cloudElementPrecipTotal':floating-point representing the sum of all rainfall in CE if TRMMdirName entered,
							'cloudElementLatLonTRMM':(lat,lon,value) of TRMM data in CE if TRMMdirName entered, 
							'TRMMArea': floating-point representing the CE if TRMMdirName entered,
							'CETRMMmax':floating-point representing the max rate in the CE if TRMMdirName entered, 
							'CETRMMmin':floating-point representing the min rate in the CE if TRMMdirName entered}
	Assumptions::
	    Assumes we are dealing with MERG data which is 4kmx4km resolved, thus the smallest value 
        required according to Vila et al. (2008) is 2400km^2 
        therefore, 2400/16 = 150 contiguous squares
	'''

	print "mergImgs shape ", mergImgs.shape
	print "timelist is ", timelist

	frame = ma.empty((1,mergImgs.shape[1],mergImgs.shape[2]))
	CEcounter = 0
	frameCEcounter = 0
	frameNum = 0
	cloudElementEpsilon = 0.0
	cloudElementDict = {} 
	cloudElementCenter = []		#list with two elements [lat,lon] for the center of a CE
	prevFrameCEs = []			#list for CEs in previous frame
	currFrameCEs = []			#list for CEs in current frame
	cloudElementLat = []		#list for a particular CE's lat values
	cloudElementLon = []		#list for a particular CE's lon values
	cloudElementLatLons = []	#list for a particular CE's (lat,lon) values
	
	prevLatValue = 0.0
	prevLonValue = 0.0
	TIR_min = 0.0
	TIR_max = 0.0
	temporalRes = 3 # TRMM data is 3 hourly
	precipTotal = 0.0
	CETRMMList =[]
	precip =[]
	TRMMCloudElementLatLons =[]

	minCELatLimit = 0.0
	minCELonLimit = 0.0
	maxCELatLimit = 0.0
	maxCELonLimit = 0.0
	
	nygrd = len(LAT[:, 0]); nxgrd = len(LON[0, :])
	
	#openfile for storing ALL cloudElement information 
	cloudElementsFile = open((MAINDIRECTORY+'/textFiles/cloudElements.txt'),'wb')
	#openfile for storing cloudElement information meeting user criteria i.e. MCCs in this case
	cloudElementsUserFile = open((MAINDIRECTORY+'/textFiles/cloudElementsUserFile.txt'),'w')
	
	#NB in the TRMM files the info is hours since the time thus 00Z file has in 01, 02 and 03 times
	for t in xrange(mergImgs.shape[0]):
		#-------------------------------------------------
		# #textfile name for saving the data for arcgis
		# thisFileName = MAINDIRECTORY+'/' + (str(timelist[t])).replace(" ", "_") + '.txt'
		# cloudElementsTextFile = open(thisFileName,'w')
		#-------------------------------------------------

		#determine contiguous locations with temeperature below the warmest temp i.e. cloudElements in each frame
	   	frame, CEcounter = ndimage.measurements.label(mergImgs[t,:,:], structure=STRUCTURING_ELEMENT)
	   	frameCEcounter=0
		frameNum += 1

		#for each of the areas identified, check to determine if it a valid CE via an area and T requirement
	   	for count in xrange(CEcounter):
	   		#[0] is time dimension. Determine the actual values from the data
	   		#loc is a masked array
	   		try:
	   			loc = ndimage.find_objects(frame==(count+1))[0]
	   		except Exception, e:
	   			print "Error is ", e
	   			continue


	   		cloudElement = mergImgs[t,:,:][loc]
	   		labels, lcounter = ndimage.label(cloudElement)
	   		
	   		#determine the true lats and lons for this particular CE
   			cloudElementLat = LAT[loc[0],0]
   			cloudElementLon = LON[0,loc[1]] 
   			
	   		#determine number of boxes in this cloudelement
	   		numOfBoxes = np.count_nonzero(cloudElement)
	   		cloudElementArea = numOfBoxes*XRES*YRES

	   		#If the area is greater than the area required, or if the area is smaller than the suggested area, check if it meets a convective fraction requirement
	   		#consider as CE

	   		if cloudElementArea >= AREA_MIN or (cloudElementArea < AREA_MIN and ((ndimage.minimum(cloudElement, labels=labels))/float((ndimage.maximum(cloudElement, labels=labels)))) < CONVECTIVE_FRACTION ):

	   			#get some time information and labeling info
	   			frameTime = str(timelist[t])
	   			frameCEcounter +=1
	   			CEuniqueID = 'F'+str(frameNum)+'CE'+str(frameCEcounter) 

	   			#-------------------------------------------------
	    		#textfile name for accesing CE data using MATLAB code
				# thisFileName = MAINDIRECTORY+'/' + (str(timelist[t])).replace(" ", "_") + CEuniqueID +'.txt'
				# cloudElementsTextFile = open(thisFileName,'w')
				#-------------------------------------------------

				# ------ NETCDF File stuff for brightness temp stuff ------------------------------------
				thisFileName = MAINDIRECTORY +'/MERGnetcdfCEs/cloudElements'+ (str(timelist[t])).replace(" ", "_") + CEuniqueID +'.nc'
				currNetCDFCEData = Dataset(thisFileName, 'w', format='NETCDF4')
				currNetCDFCEData.description = 'Cloud Element '+CEuniqueID + ' temperature data'
				currNetCDFCEData.calendar = 'standard'
				currNetCDFCEData.conventions = 'COARDS'
				# dimensions
				currNetCDFCEData.createDimension('time', None)
				currNetCDFCEData.createDimension('lat', len(LAT[:,0]))
				currNetCDFCEData.createDimension('lon', len(LON[0,:]))
				# variables
				tempDims = ('time','lat', 'lon',)
				times = currNetCDFCEData.createVariable('time', 'f8', ('time',))
				times.units = 'hours since '+ str(timelist[t])[:-6]
				latitudes = currNetCDFCEData.createVariable('latitude', 'f8', ('lat',))
				longitudes = currNetCDFCEData.createVariable('longitude', 'f8', ('lon',))
				brightnesstemp = currNetCDFCEData.createVariable('brightnesstemp', 'i16',tempDims )
				brightnesstemp.units = 'Kelvin'
				# NETCDF data
				dates=[timelist[t]+timedelta(hours=0)]
				times[:] =  date2num(dates,units=times.units)
				longitudes[:] = LON[0,:]
				longitudes.units = "degrees_east" 
				longitudes.long_name = "Longitude" 

				latitudes[:] =  LAT[:,0]
				latitudes.units = "degrees_north"
				latitudes.long_name ="Latitude"
				
				#generate array of zeros for brightness temperature
				brightnesstemp1 = ma.zeros((1,len(latitudes), len(longitudes))).astype('int16')
				#-----------End most of NETCDF file stuff ------------------------------------

				#if other dataset (TRMM) assumed to be a precipitation dataset was entered
				if TRMMdirName:
					#------------------TRMM stuff -------------------------------------------------
					fileDate = ((str(timelist[t])).replace(" ", "")[:-8]).replace("-","")
					fileHr1 = (str(timelist[t])).replace(" ", "")[-8:-6]
					
					if int(fileHr1) % temporalRes == 0:
						fileHr = fileHr1
					else:
						fileHr = (int(fileHr1)/temporalRes) * temporalRes
					if fileHr < 10:
						fileHr = '0'+str(fileHr)
					else:
						str(fileHr)

					#open TRMM file for the resolution info and to create the appropriate sized grid
					TRMMfileName = TRMMdirName+'/3B42.'+ fileDate + "."+str(fileHr)+".7A.nc"
					
					TRMMData = Dataset(TRMMfileName,'r', format='NETCDF4')
					precipRate = TRMMData.variables['pcp'][:,:,:]
					latsrawTRMMData = TRMMData.variables['latitude'][:]
					lonsrawTRMMData = TRMMData.variables['longitude'][:]
					lonsrawTRMMData[lonsrawTRMMData > 180] = lonsrawTRMMData[lonsrawTRMMData>180] - 360.
					LONTRMM, LATTRMM = np.meshgrid(lonsrawTRMMData, latsrawTRMMData)

					nygrdTRMM = len(LATTRMM[:,0]); nxgrdTRMM = len(LONTRMM[0,:])
					precipRateMasked = ma.masked_array(precipRate, mask=(precipRate < 0.0))
					#---------regrid the TRMM data to the MERG dataset ----------------------------------
					#regrid using the do_regrid stuff from the Apache OCW 
					regriddedTRMM = ma.zeros((0, nygrd, nxgrd))
					regriddedTRMM = process.do_regrid(precipRateMasked[0,:,:], LATTRMM,  LONTRMM, LAT, LON, order=1, mdi= -999999999)
					#----------------------------------------------------------------------------------
		
					# #get the lat/lon info from cloudElement
					#get the lat/lon info from the file
					latCEStart = LAT[0][0]
					latCEEnd = LAT[-1][0]
					lonCEStart = LON[0][0]
					lonCEEnd = LON[0][-1]
					
					#get the lat/lon info for TRMM data (different resolution)
					latStartT = find_nearest(latsrawTRMMData, latCEStart)
					latEndT = find_nearest(latsrawTRMMData, latCEEnd)
					lonStartT = find_nearest(lonsrawTRMMData, lonCEStart)
					lonEndT = find_nearest(lonsrawTRMMData, lonCEEnd)
					latStartIndex = np.where(latsrawTRMMData == latStartT)
					latEndIndex = np.where(latsrawTRMMData == latEndT)
					lonStartIndex = np.where(lonsrawTRMMData == lonStartT)
					lonEndIndex = np.where(lonsrawTRMMData == lonEndT)

					#get the relevant TRMM info 
					CEprecipRate = precipRate[:,(latStartIndex[0][0]-1):latEndIndex[0][0],(lonStartIndex[0][0]-1):lonEndIndex[0][0]]
					TRMMData.close()
					
					# ------ NETCDF File info for writing TRMM CE rainfall ------------------------------------
					thisFileName = MAINDIRECTORY+'/TRMMnetcdfCEs/TRMM' + (str(timelist[t])).replace(" ", "_") + CEuniqueID +'.nc'
					currNetCDFTRMMData = Dataset(thisFileName, 'w', format='NETCDF4')
					currNetCDFTRMMData.description = 'Cloud Element '+CEuniqueID + ' precipitation data'
					currNetCDFTRMMData.calendar = 'standard'
					currNetCDFTRMMData.conventions = 'COARDS'
					# dimensions
					currNetCDFTRMMData.createDimension('time', None)
					currNetCDFTRMMData.createDimension('lat', len(LAT[:,0]))
					currNetCDFTRMMData.createDimension('lon', len(LON[0,:]))
					
					# variables
					TRMMprecip = ('time','lat', 'lon',)
					times = currNetCDFTRMMData.createVariable('time', 'f8', ('time',))
					times.units = 'hours since '+ str(timelist[t])[:-6]
					latitude = currNetCDFTRMMData.createVariable('latitude', 'f8', ('lat',))
					longitude = currNetCDFTRMMData.createVariable('longitude', 'f8', ('lon',))
					rainFallacc = currNetCDFTRMMData.createVariable('precipitation_Accumulation', 'f8',TRMMprecip )
					rainFallacc.units = 'mm'

					longitude[:] = LON[0,:]
					longitude.units = "degrees_east" 
					longitude.long_name = "Longitude" 

					latitude[:] =  LAT[:,0]
					latitude.units = "degrees_north"
					latitude.long_name ="Latitude"

					finalCETRMMvalues = ma.zeros((brightnesstemp.shape))
					#-----------End most of NETCDF file stuff ------------------------------------

	   			#populate cloudElementLatLons by unpacking the original values from loc to get the actual value for lat and lon
    			#TODO: KDW - too dirty... play with itertools.izip or zip and the enumerate with this
    			# 			as cloudElement is masked
				for index,value in np.ndenumerate(cloudElement):
					if value != 0 : 
						lat_index,lon_index = index
						lat_lon_tuple = (cloudElementLat[lat_index], cloudElementLon[lon_index],value)

						#generate the comma separated file for GIS
						cloudElementLatLons.append(lat_lon_tuple)

						#temp data for CE NETCDF file
						brightnesstemp1[0,int(np.where(LAT[:,0]==cloudElementLat[lat_index])[0]),int(np.where(LON[0,:]==cloudElementLon[lon_index])[0])] = value
						
						if TRMMdirName:
							finalCETRMMvalues[0,int(np.where(LAT[:,0]==cloudElementLat[lat_index])[0]),int(np.where(LON[0,:]==cloudElementLon[lon_index])[0])] = regriddedTRMM[int(np.where(LAT[:,0]==cloudElementLat[lat_index])[0]),int(np.where(LON[0,:]==cloudElementLon[lon_index])[0])]
							CETRMMList.append((cloudElementLat[lat_index], cloudElementLon[lon_index], finalCETRMMvalues[0,cloudElementLat[lat_index], cloudElementLon[lon_index]]))


				brightnesstemp[:] = brightnesstemp1[:]
				currNetCDFCEData.close()

				if TRMMdirName:

					#calculate the total precip associated with the feature
					for index, value in np.ndenumerate(finalCETRMMvalues):
						precipTotal += value 
	    				precip.append(value)
			
					rainFallacc[:] = finalCETRMMvalues[:]
					currNetCDFTRMMData.close()
					TRMMnumOfBoxes = np.count_nonzero(finalCETRMMvalues)
					TRMMArea = TRMMnumOfBoxes*XRES*YRES
					try:
						maxCEprecipRate = np.max(finalCETRMMvalues[np.nonzero(finalCETRMMvalues)])
						minCEprecipRate = np.min(finalCETRMMvalues[np.nonzero(finalCETRMMvalues)])
					except:
						pass

				#sort cloudElementLatLons by lats
				cloudElementLatLons.sort(key=lambda tup: tup[0])	

				#determine if the cloud element the shape 
				cloudElementEpsilon = eccentricity (cloudElement)
	   			cloudElementsUserFile.write("\n\nTime is: %s" %(str(timelist[t])))
	   			cloudElementsUserFile.write("\nCEuniqueID is: %s" %CEuniqueID)
	   			latCenter, lonCenter = ndimage.measurements.center_of_mass(cloudElement, labels=labels)
	   			
	   			#latCenter and lonCenter are given according to the particular array defining this CE
	   			#so you need to convert this value to the overall domain truth
	   			latCenter = cloudElementLat[round(latCenter)]
	   			lonCenter = cloudElementLon[round(lonCenter)]
	   			cloudElementsUserFile.write("\nCenter (lat,lon) is: %.2f\t%.2f" %(latCenter, lonCenter))
	   			cloudElementCenter.append(latCenter)
	   			cloudElementCenter.append(lonCenter)
	   			cloudElementsUserFile.write("\nNumber of boxes are: %d" %numOfBoxes)
	   			cloudElementsUserFile.write("\nArea is: %.4f km^2" %(cloudElementArea))
				cloudElementsUserFile.write("\nAverage brightness temperature is: %.4f K" %ndimage.mean(cloudElement, labels=labels))
				cloudElementsUserFile.write("\nMin brightness temperature is: %.4f K" %ndimage.minimum(cloudElement, labels=labels))
				cloudElementsUserFile.write("\nMax brightness temperature is: %.4f K" %ndimage.maximum(cloudElement, labels=labels))
				cloudElementsUserFile.write("\nBrightness temperature variance is: %.4f K" %ndimage.variance(cloudElement, labels=labels))
				cloudElementsUserFile.write("\nConvective fraction is: %.4f " %(((ndimage.minimum(cloudElement, labels=labels))/float((ndimage.maximum(cloudElement, labels=labels))))*100.0))
				cloudElementsUserFile.write("\nEccentricity is: %.4f " %(cloudElementEpsilon))
				#populate the dictionary
				if TRMMdirName:
					cloudElementDict = {'uniqueID': CEuniqueID, 'cloudElementTime': timelist[t],'cloudElementLatLon': cloudElementLatLons, 'cloudElementCenter':cloudElementCenter, 'cloudElementArea':cloudElementArea, 'cloudElementEccentricity':cloudElementEpsilon, 'cloudElementTmax':TIR_max, 'cloudElementTmin': TIR_min, 'cloudElementPrecipTotal':precipTotal,'cloudElementLatLonTRMM':CETRMMList, 'TRMMArea': TRMMArea,'CETRMMmax':maxCEprecipRate, 'CETRMMmin':minCEprecipRate}
				else:
					cloudElementDict = {'uniqueID': CEuniqueID, 'cloudElementTime': timelist[t],'cloudElementLatLon': cloudElementLatLons, 'cloudElementCenter':cloudElementCenter, 'cloudElementArea':cloudElementArea, 'cloudElementEccentricity':cloudElementEpsilon, 'cloudElementTmax':TIR_max, 'cloudElementTmin': TIR_min,}
				
				#current frame list of CEs
				currFrameCEs.append(cloudElementDict)
				
				#draw the graph node
				CLOUD_ELEMENT_GRAPH.add_node(CEuniqueID, cloudElementDict)
				
				if frameNum != 1:
					for cloudElementDict in prevFrameCEs:
						thisCElen = len(cloudElementLatLons)
						percentageOverlap, areaOverlap = cloudElementOverlap(cloudElementLatLons, cloudElementDict['cloudElementLatLon'])
						
						#change weights to integers because the built in shortest path chokes on floating pts according to Networkx doc
						#according to Goyens et al, two CEs are considered related if there is atleast 95% overlap between them for consecutive imgs a max of 2 hrs apart
						if percentageOverlap >= 0.95: 
							CLOUD_ELEMENT_GRAPH.add_edge(cloudElementDict['uniqueID'], CEuniqueID, weight=edgeWeight[0])
							
						elif percentageOverlap >= 0.90 and percentageOverlap < 0.95 :
							CLOUD_ELEMENT_GRAPH.add_edge(cloudElementDict['uniqueID'], CEuniqueID, weight=edgeWeight[1])

						elif areaOverlap >= MIN_OVERLAP:
							CLOUD_ELEMENT_GRAPH.add_edge(cloudElementDict['uniqueID'], CEuniqueID, weight=edgeWeight[2])

    			else:
    				#TODO: remove this else as we only wish for the CE details
    				#ensure only the non-zero elements are considered
    				#store intel in allCE file
    				labels, _ = ndimage.label(cloudElement)
    				cloudElementsFile.write("\n-----------------------------------------------")
    				cloudElementsFile.write("\n\nTime is: %s" %(str(timelist[t])))
    				# cloudElementLat = LAT[loc[0],0]
    				# cloudElementLon = LON[0,loc[1]] 
    				
    				#populate cloudElementLatLons by unpacking the original values from loc
    				#TODO: KDW - too dirty... play with itertools.izip or zip and the enumerate with this
    				# 			as cloudElement is masked
    				for index,value in np.ndenumerate(cloudElement):
    					if value != 0 : 
    						lat_index,lon_index = index
    						lat_lon_tuple = (cloudElementLat[lat_index], cloudElementLon[lon_index])
    						cloudElementLatLons.append(lat_lon_tuple)
	
    				cloudElementsFile.write("\nLocation of rejected CE (lat,lon) points are: %s" %cloudElementLatLons)
    				#latCenter and lonCenter are given according to the particular array defining this CE
		   			#so you need to convert this value to the overall domain truth
    				latCenter, lonCenter = ndimage.measurements.center_of_mass(cloudElement, labels=labels)
    				latCenter = cloudElementLat[round(latCenter)]
    				lonCenter = cloudElementLon[round(lonCenter)]
    				cloudElementsFile.write("\nCenter (lat,lon) is: %.2f\t%.2f" %(latCenter, lonCenter))
    				cloudElementsFile.write("\nNumber of boxes are: %d" %numOfBoxes)
    				cloudElementsFile.write("\nArea is: %.4f km^2" %(cloudElementArea))
    				cloudElementsFile.write("\nAverage brightness temperature is: %.4f K" %ndimage.mean(cloudElement, labels=labels))
    				cloudElementsFile.write("\nMin brightness temperature is: %.4f K" %ndimage.minimum(cloudElement, labels=labels))
    				cloudElementsFile.write("\nMax brightness temperature is: %.4f K" %ndimage.maximum(cloudElement, labels=labels))
    				cloudElementsFile.write("\nBrightness temperature variance is: %.4f K" %ndimage.variance(cloudElement, labels=labels))
    				cloudElementsFile.write("\nConvective fraction is: %.4f " %(((ndimage.minimum(cloudElement, labels=labels))/float((ndimage.maximum(cloudElement, labels=labels))))*100.0))
    				cloudElementsFile.write("\nEccentricity is: %.4f " %(cloudElementEpsilon))
    				cloudElementsFile.write("\n-----------------------------------------------")
    				
			#reset list for the next CE
			nodeExist = False
			cloudElementCenter=[]
			cloudElement = []
			cloudElementLat=[]
			cloudElementLon =[]
			cloudElementLatLons =[]
			brightnesstemp1 =[]
			brightnesstemp =[]
			finalCETRMMvalues =[]
			CEprecipRate =[]
			CETRMMList =[]
			precipTotal = 0.0
			precip=[]
			TRMMCloudElementLatLons=[]
			
		#reset for the next time
		prevFrameCEs =[]
		prevFrameCEs = currFrameCEs
		currFrameCEs =[]
		    			
	cloudElementsFile.close
	cloudElementsUserFile.close
	#if using ARCGIS data store code, uncomment this file close line
	#cloudElementsTextFile.close

	#clean up graph - remove parent and childless nodes
	outAndInDeg = CLOUD_ELEMENT_GRAPH.degree_iter()
	toRemove = [node[0] for node in outAndInDeg if node[1]<1]
	CLOUD_ELEMENT_GRAPH.remove_nodes_from(toRemove)
	
	print "number of nodes are: ", CLOUD_ELEMENT_GRAPH.number_of_nodes()
	print "number of edges are: ", CLOUD_ELEMENT_GRAPH.number_of_edges()
	print ("*"*80)

	#hierachial graph output
	graphTitle = "Cloud Elements observed over somewhere from 0000Z to 0000Z" 
	drawGraph(CLOUD_ELEMENT_GRAPH, graphTitle, edgeWeight)

	return CLOUD_ELEMENT_GRAPH	
#******************************************************************
def findPrecipRate(TRMMdirName, timelist):
	''' 
	Purpose:: 
		Determines the precipitation rates for MCSs found if TRMMdirName was not entered in findCloudElements this can be used

	Input:: 
		TRMMdirName: a string representing the directory for the original TRMM netCDF files
		timelist: a list of python datatimes

    Output:: a list of dictionary of the TRMM data 
    	NB: also creates netCDF with TRMM data for each CE (for post processing) index
    		in MAINDIRECTORY/TRMMnetcdfCEs
   
    Assumptions:: Assumes that findCloudElements was run without the TRMMdirName value 
 
	'''
	allCEnodesTRMMdata =[]
	TRMMdataDict={}
	precipTotal = 0.0

	os.chdir((MAINDIRECTORY+'/MERGnetcdfCEs/'))
	imgFilename = ''
	temporalRes = 3 #3 hours for TRMM
	
	#sort files
	files = filter(os.path.isfile, glob.glob("*.nc"))
	files.sort(key=lambda x: os.path.getmtime(x))
	
	for afile in files:
		fullFname = os.path.splitext(afile)[0]
		noFrameExtension = (fullFname.replace("_","")).split('F')[0]
		CEuniqueID = 'F' +(fullFname.replace("_","")).split('F')[1]
		fileDateTimeChar = (noFrameExtension.replace(":","")).split('s')[1]
		fileDateTime = fileDateTimeChar.replace("-","")
		fileDate = fileDateTime[:-6]
		fileHr1=fileDateTime[-6:-4]

		cloudElementData = Dataset(afile,'r', format='NETCDF4')
		brightnesstemp1 = cloudElementData.variables['brightnesstemp'][:,:,:] 
		latsrawCloudElements = cloudElementData.variables['latitude'][:]
		lonsrawCloudElements = cloudElementData.variables['longitude'][:]
		
		brightnesstemp = np.squeeze(brightnesstemp1, axis=0)
		
		if int(fileHr1) % temporalRes == 0:
			fileHr = fileHr1
		else:
			fileHr = (int(fileHr1)/temporalRes) * temporalRes
		
		if fileHr < 10:
			fileHr = '0'+str(fileHr)
		else:
			str(fileHr)

		TRMMfileName = TRMMdirName+"/3B42."+ str(fileDate) + "."+str(fileHr)+".7A.nc"
		TRMMData = Dataset(TRMMfileName,'r', format='NETCDF4')
		precipRate = TRMMData.variables['pcp'][:,:,:]
		latsrawTRMMData = TRMMData.variables['latitude'][:]
		lonsrawTRMMData = TRMMData.variables['longitude'][:]
		lonsrawTRMMData[lonsrawTRMMData > 180] = lonsrawTRMMData[lonsrawTRMMData>180] - 360.
		LONTRMM, LATTRMM = np.meshgrid(lonsrawTRMMData, latsrawTRMMData)

		#nygrdTRMM = len(LATTRMM[:,0]); nxgrd = len(LONTRMM[0,:])
		nygrd = len(LAT[:, 0]); nxgrd = len(LON[0, :])

		precipRateMasked = ma.masked_array(precipRate, mask=(precipRate < 0.0))
		#---------regrid the TRMM data to the MERG dataset ----------------------------------
		#regrid using the do_regrid stuff from the Apache OCW 
		regriddedTRMM = ma.zeros((0, nygrd, nxgrd))
		regriddedTRMM = process.do_regrid(precipRateMasked[0,:,:], LATTRMM,  LONTRMM, LAT, LON, order=1, mdi= -999999999)
		#----------------------------------------------------------------------------------

		# #get the lat/lon info from
		latCEStart = LAT[0][0]
		latCEEnd = LAT[-1][0]
		lonCEStart = LON[0][0]
		lonCEEnd = LON[0][-1]

		#get the lat/lon info for TRMM data (different resolution)
		latStartT = find_nearest(latsrawTRMMData, latCEStart)
		latEndT = find_nearest(latsrawTRMMData, latCEEnd)
		lonStartT = find_nearest(lonsrawTRMMData, lonCEStart)
		lonEndT = find_nearest(lonsrawTRMMData, lonCEEnd)
		latStartIndex = np.where(latsrawTRMMData == latStartT)
		latEndIndex = np.where(latsrawTRMMData == latEndT)
		lonStartIndex = np.where(lonsrawTRMMData == lonStartT)
		lonEndIndex = np.where(lonsrawTRMMData == lonEndT)

		#get the relevant TRMM info 
		CEprecipRate = precipRate[:,(latStartIndex[0][0]-1):latEndIndex[0][0],(lonStartIndex[0][0]-1):lonEndIndex[0][0]]
		TRMMData.close()
			
		
		# ------ NETCDF File stuff ------------------------------------
		thisFileName = MAINDIRECTORY+'/TRMMnetcdfCEs/'+ fileDateTime + CEuniqueID +'.nc'
		currNetCDFTRMMData = Dataset(thisFileName, 'w', format='NETCDF4')
		currNetCDFTRMMData.description = 'Cloud Element '+CEuniqueID + ' rainfall data'
		currNetCDFTRMMData.calendar = 'standard'
		currNetCDFTRMMData.conventions = 'COARDS'
		# dimensions
		currNetCDFTRMMData.createDimension('time', None)
		currNetCDFTRMMData.createDimension('lat', len(LAT[:,0]))
		currNetCDFTRMMData.createDimension('lon', len(LON[0,:]))
		# variables
		TRMMprecip = ('time','lat', 'lon',)
		times = currNetCDFTRMMData.createVariable('time', 'f8', ('time',))
		times.units = 'hours since '+ fileDateTime[:-6] 
		latitude = currNetCDFTRMMData.createVariable('latitude', 'f8', ('lat',))
		longitude = currNetCDFTRMMData.createVariable('longitude', 'f8', ('lon',))
		rainFallacc = currNetCDFTRMMData.createVariable('precipitation_Accumulation', 'f8',TRMMprecip )
		rainFallacc.units = 'mm'

		longitude[:] = LON[0,:]
		longitude.units = "degrees_east" 
		longitude.long_name = "Longitude" 

		latitude[:] =  LAT[:,0]
		latitude.units = "degrees_north"
		latitude.long_name ="Latitude"

		finalCETRMMvalues = ma.zeros((brightnesstemp1.shape))
		#-----------End most of NETCDF file stuff ------------------------------------	
		for index,value in np.ndenumerate(brightnesstemp):
			lat_index, lon_index = index
			currTimeValue = 0
			if value > 0:

				finalCETRMMvalues[0,lat_index,lon_index] = regriddedTRMM[int(np.where(LAT[:,0]==LAT[lat_index,0])[0]), int(np.where(LON[0,:]==LON[0,lon_index])[0])]
				

		rainFallacc[:] = finalCETRMMvalues
		currNetCDFTRMMData.close()

		for index, value in np.ndenumerate(finalCETRMMvalues):
			precipTotal += value 

		TRMMnumOfBoxes = np.count_nonzero(finalCETRMMvalues)
		TRMMArea = TRMMnumOfBoxes*XRES*YRES	

		try:
			minCEprecipRate = np.min(finalCETRMMvalues[np.nonzero(finalCETRMMvalues)])
		except:
			minCEprecipRate = 0.0

		try:
			maxCEprecipRate = np.max(finalCETRMMvalues[np.nonzero(finalCETRMMvalues)])
		except:
			maxCEprecipRate = 0.0

		#add info to CLOUDELEMENTSGRAPH
		#TODO try block
		for eachdict in CLOUD_ELEMENT_GRAPH.nodes(CEuniqueID):
			if eachdict[1]['uniqueID'] == CEuniqueID:
				if not 'cloudElementPrecipTotal' in eachdict[1].keys():
					eachdict[1]['cloudElementPrecipTotal'] = precipTotal
				if not 'cloudElementLatLonTRMM' in eachdict[1].keys():
					eachdict[1]['cloudElementLatLonTRMM'] = finalCETRMMvalues
				if not 'TRMMArea' in eachdict[1].keys():
					eachdict[1]['TRMMArea'] = TRMMArea
				if not 'CETRMMmin' in eachdict[1].keys():
					eachdict[1]['CETRMMmin'] = minCEprecipRate
				if not 'CETRMMmax' in eachdict[1].keys():
					eachdict[1]['CETRMMmax'] = maxCEprecipRate

		#clean up
		precipTotal = 0.0
		latsrawTRMMData =[]
		lonsrawTRMMData = []
		latsrawCloudElements=[]
		lonsrawCloudElements=[]
		finalCETRMMvalues =[]
		CEprecipRate =[]
		brightnesstemp =[]
		TRMMdataDict ={}

	return allCEnodesTRMMdata
#******************************************************************	
def findCloudClusters(CEGraph):
	'''
	Purpose:: 
		Determines the cloud clusters properties from the subgraphs in 
	    the graph i.e. prunes the graph according to the minimum depth

	Input:: 
		CEGraph: a Networkx directed graph of the CEs with weighted edges
		according the area overlap between nodes (CEs) of consectuive frames
    
    Output:: 
    	PRUNED_GRAPH: a Networkx directed graph of with CCs/ MCSs

	'''

	seenNode = []
	allMCSLists =[]
	pathDictList =[]
	pathList=[]

	cloudClustersFile = open((MAINDIRECTORY+'/textFiles/cloudClusters.txt'),'wb')
	
	for eachNode in CEGraph:
		#check if the node has been seen before
		if eachNode not in dict(enumerate(zip(*seenNode))):
			#look for all trees associated with node as the root
			thisPathDistanceAndLength = nx.single_source_dijkstra(CEGraph, eachNode)
			#determine the actual shortestPath and minimum depth/length
			maxDepthAndMinPath = findMaxDepthAndMinPath(thisPathDistanceAndLength)
			if maxDepthAndMinPath:
				maxPathLength = maxDepthAndMinPath[0] 
				shortestPath = maxDepthAndMinPath[1]
				
				#add nodes and paths to PRUNED_GRAPH
				for i in xrange(len(shortestPath)):
					if PRUNED_GRAPH.has_node(shortestPath[i]) is False:
						PRUNED_GRAPH.add_node(shortestPath[i])
						
					#add edge if necessary
					if i < (len(shortestPath)-1) and PRUNED_GRAPH.has_edge(shortestPath[i], shortestPath[i+1]) is False:
						prunedGraphEdgeweight = CEGraph.get_edge_data(shortestPath[i], shortestPath[i+1])['weight']
						PRUNED_GRAPH.add_edge(shortestPath[i], shortestPath[i+1], weight=prunedGraphEdgeweight)

				#note information in a file for consideration later i.e. checking to see if it works
				cloudClustersFile.write("\nSubtree pathlength is %d and path is %s" %(maxPathLength, shortestPath))
				#update seenNode info
				seenNode.append(shortestPath)	

	print "pruned graph"
	print "number of nodes are: ", PRUNED_GRAPH.number_of_nodes()
	print "number of edges are: ", PRUNED_GRAPH.number_of_edges()
	print ("*"*80)		
					
	graphTitle = "Cloud Clusters observed over somewhere during sometime"
	drawGraph(PRUNED_GRAPH, graphTitle, edgeWeight)
	cloudClustersFile.close
	
	return PRUNED_GRAPH  
#******************************************************************
def findMCC (prunedGraph):
	'''
	Purpose:: 
		Determines if subtree is a MCC according to Laurent et al 1998 criteria

	Input:: 
		prunedGraph: a Networkx Graph representing the CCs 

    Output:: 
    	finalMCCList: a list of list of tuples representing a MCC
             
    Assumptions: 
    	frames are ordered and are equally distributed in time e.g. hrly satellite images
 
	'''
	MCCList = []
	MCSList = []
	definiteMCC = []
	definiteMCS = []
	eachList =[]
	eachMCCList =[]
	maturing = False
	decaying = False
	fNode = ''
	lNode = ''
	removeList =[]
	imgCount = 0
	imgTitle =''
	
	maxShieldNode = ''
	orderedPath =[]
	treeTraversalList =[]
	definiteMCCFlag = False
	unDirGraph = nx.Graph()
	aSubGraph = nx.DiGraph()
	definiteMCSFlag = False

	
	#connected_components is not available for DiGraph, so generate graph as undirected 
	unDirGraph = PRUNED_GRAPH.to_undirected()
	subGraph = nx.connected_component_subgraphs(unDirGraph)

	#for each path in the subgraphs determined
	for path in subGraph:
		#definite is a subTree provided the duration is longer than 3 hours

		if len(path.nodes()) > MIN_MCS_DURATION:
			orderedPath = path.nodes()
			orderedPath.sort(key=lambda item:(len(item.split('C')[0]), item.split('C')[0]))
			#definiteMCS.append(orderedPath)

			#build back DiGraph for checking purposes/paper purposes
			aSubGraph.add_nodes_from(path.nodes())	
			for eachNode in path.nodes():
				if prunedGraph.predecessors(eachNode):
					for node in prunedGraph.predecessors(eachNode):
						aSubGraph.add_edge(node,eachNode,weight=edgeWeight[0])

				if prunedGraph.successors(eachNode):
					for node in prunedGraph.successors(eachNode):
						aSubGraph.add_edge(eachNode,node,weight=edgeWeight[0])
			imgTitle = 'CC'+str(imgCount+1)
			drawGraph(aSubGraph, imgTitle, edgeWeight) #for eachNode in path:
			imgCount +=1
			#----------end build back ---------------------------------------------

			mergeList, splitList = hasMergesOrSplits(path)	
			#add node behavior regarding neutral, merge, split or both
			for node in path:
				if node in mergeList and node in splitList:
					addNodeBehaviorIdentifier(node,'B')
				elif node in mergeList and not node in splitList:
					addNodeBehaviorIdentifier(node,'M')
				elif node in splitList and not node in mergeList:
					addNodeBehaviorIdentifier(node,'S')
				else:
					addNodeBehaviorIdentifier(node,'N')
			

			#Do the first part of checking for the MCC feature
			#find the path
			treeTraversalList = traverseTree(aSubGraph, orderedPath[0],[],[])
			#print "treeTraversalList is ", treeTraversalList
			#check the nodes to determine if a MCC on just the area criteria (consecutive nodes meeting the area and temp requirements)
			MCCList = checkedNodesMCC(prunedGraph, treeTraversalList)
			for aDict in MCCList:
				for eachNode in aDict["fullMCSMCC"]:
					addNodeMCSIdentifier(eachNode[0],eachNode[1])
				
			#do check for if MCCs overlap
			if MCCList:
				if len(MCCList) > 1:
					for count in range(len(MCCList)): #for eachDict in MCCList:
						#if there are more than two lists
						if count >= 1:
							#and the first node in this list
							eachList = list(x[0] for x in MCCList[count]["possMCCList"])
							eachList.sort(key=lambda nodeID:(len(nodeID.split('C')[0]), nodeID.split('C')[0]))
							if eachList:
								fNode = eachList[0]
								#get the lastNode in the previous possMCC list
								eachList = list(x[0] for x in MCCList[(count-1)]["possMCCList"])
								eachList.sort(key=lambda nodeID:(len(nodeID.split('C')[0]), nodeID.split('C')[0]))
								if eachList:
									lNode = eachList[-1]
									if lNode in CLOUD_ELEMENT_GRAPH.predecessors(fNode):
										for aNode in CLOUD_ELEMENT_GRAPH.predecessors(fNode):
											if aNode in eachList and aNode == lNode:
												#if edge_data is equal or less than to the exisitng edge in the tree append one to the other
												if CLOUD_ELEMENT_GRAPH.get_edge_data(aNode,fNode)['weight'] <= CLOUD_ELEMENT_GRAPH.get_edge_data(lNode,fNode)['weight']:
													MCCList[count-1]["possMCCList"].extend(MCCList[count]["possMCCList"]) 
													MCCList[count-1]["fullMCSMCC"].extend(MCCList[count]["fullMCSMCC"])
													MCCList[count-1]["durationAandB"] +=  MCCList[count]["durationAandB"]
													MCCList[count-1]["CounterCriteriaA"] += MCCList[count]["CounterCriteriaA"]
													MCCList[count-1]["highestMCCnode"] = MCCList[count]["highestMCCnode"]
													MCCList[count-1]["frameNum"] = MCCList[count]["frameNum"] 
													removeList.append(count)
				#update the MCCList
				if removeList:
					for i in removeList:
						if (len(MCCList)-1) > i:
							del MCCList[i]
							removeList =[]
				
			#check if the nodes also meet the duration criteria and the shape crieria
			for eachDict in MCCList:
				#order the fullMCSMCC list, then run maximum extent and eccentricity criteria 
				if (eachDict["durationAandB"] * TRES) >= MINIMUM_DURATION and (eachDict["durationAandB"] * TRES) <= MAXIMUM_DURATION:
					eachList = list(x[0] for x in eachDict["fullMCSMCC"])
					eachList.sort(key=lambda nodeID:(len(nodeID.split('C')[0]), nodeID.split('C')[0]))
					eachMCCList = list(x[0] for x in eachDict["possMCCList"])
					eachMCCList.sort(key=lambda nodeID:(len(nodeID.split('C')[0]), nodeID.split('C')[0]))
					
					#update the nodemcsidentifer behavior
					#find the first element eachMCCList in eachList, and ensure everything ahead of it is indicated as 'I', 
					#find last element in eachMCCList in eachList and ensure everything after it is indicated as 'D'
					#ensure that everything between is listed as 'M'
					for eachNode in eachList[:(eachList.index(eachMCCList[0]))]: 
						addNodeMCSIdentifier(eachNode,'I')

					addNodeMCSIdentifier(eachMCCList[0],'M')

					for eachNode in eachList[(eachList.index(eachMCCList[-1])+1):]:
						addNodeMCSIdentifier(eachNode, 'D')

					#update definiteMCS list
					for eachNode in orderedPath[(orderedPath.index(eachMCCList[-1])+1):]:
						addNodeMCSIdentifier(eachNode, 'D')

					#run maximum extent and eccentricity criteria
					maxExtentNode, definiteMCCFlag = maxExtentAndEccentricity(eachList)
					#print "maxExtentNode, definiteMCCFlag ", maxExtentNode, definiteMCCFlag
					if definiteMCCFlag == True:
						definiteMCC.append(eachList)


			definiteMCS.append(orderedPath)
			
			#reset for next subGraph	
			aSubGraph.clear()
			orderedPath=[]
			MCCList =[]
			MCSList =[]
			definiteMCSFlag = False
		
	return definiteMCC, definiteMCS
#******************************************************************
def traverseTree(subGraph,node, stack, checkedNodes=None):
	'''
	Purpose:: 
		To traverse a tree using a modified depth-first iterative deepening (DFID) search algorithm 

	Input:: 
		subGraph: a Networkx DiGraph representing a CC
			lengthOfsubGraph: an integer representing the length of the subgraph
			node: a string representing the node currently being checked
			stack: a list of strings representing a list of nodes in a stack functionality 
					i.e. Last-In-First-Out (LIFO) for sorting the information from each visited node
			checkedNodes: a list of strings representing the list of the nodes in the traversal
    
    Output:: 
    	checkedNodes: a list of strings representing the list of the nodes in the traversal

    Assumptions: 
    	frames are ordered and are equally distributed in time e.g. hrly satellite images
 
	'''
	if len(checkedNodes) == len(subGraph):
		return checkedNodes

	if not checkedNodes:
		stack =[]
		checkedNodes.append(node)
		
	#check one level infront first...if something does exisit, stick it at the front of the stack
	upOneLevel = subGraph.predecessors(node)
	downOneLevel = subGraph.successors(node)
	for parent in upOneLevel:
		if parent not in checkedNodes and parent not in stack:
			for child in downOneLevel:
				if child not in checkedNodes and child not in stack:
					stack.insert(0,child)
		
			stack.insert(0,parent)	

	for child in downOneLevel:
		if child not in checkedNodes and child not in stack:
			if len(subGraph.predecessors(child)) > 1 or node in checkedNodes:
				stack.insert(0,child)
			else:
				stack.append(child)		
	
	for eachNode in stack:
		if eachNode not in checkedNodes:
			checkedNodes.append(eachNode)
			return traverseTree(subGraph, eachNode, stack, checkedNodes)
	
	return checkedNodes 
#******************************************************************
def checkedNodesMCC (prunedGraph, nodeList):
	'''
	Purpose :: 
		Determine if this path is (or is part of) a MCC and provides 
	    preliminary information regarding the stages of the feature

	Input:: 
		prunedGraph: a Networkx Graph representing all the cloud clusters 
		nodeList: list of strings (CE ID) from the traversal
		
	Output:: 
		potentialMCCList: list of dictionaries representing all possible MCC within the path
			dictionary = {"possMCCList":[(node,'I')], "fullMCSMCC":[(node,'I')], "CounterCriteriaA": CounterCriteriaA, "durationAandB": durationAandB}
	'''
	
	CounterCriteriaAFlag = False
	CounterCriteriaBFlag = False
	INITIATIONFLAG = False
	MATURITYFLAG = False
	DECAYFLAG = False
	thisdict = {} #will have the same items as the cloudElementDict 
	cloudElementAreaB = 0.0
	cloudElementAreaA = 0.0
	epsilon = 0.0
	frameNum =0
	oldNode =''
	potentialMCCList =[]
	durationAandB = 0

	#check for if the list contains only one string/node
	if type(nodeList) is str:
		oldNode=nodeList
		nodeList =[]
		nodeList.append(oldNode)

	for node in nodeList:
		thisdict = thisDict(node)
		CounterCriteriaAFlag = False
		CounterCriteriaBFlag = False
		existingFrameFlag = False

		if thisdict['cloudElementArea'] >= OUTER_CLOUD_SHIELD_AREA:
			CounterCriteriaAFlag = True
			INITIATIONFLAG = True
			MATURITYFLAG = False

			#check if criteriaA is met
			cloudElementAreaA, criteriaA = checkCriteria(thisdict['cloudElementLatLon'], OUTER_CLOUD_SHIELD_TEMPERATURE)
			#TODO: calcuate the eccentricity at this point and read over????or create a new field in the dict
			
			if cloudElementAreaA >= OUTER_CLOUD_SHIELD_AREA:
				#check if criteriaB is met
				cloudElementAreaB,criteriaB = checkCriteria(thisdict['cloudElementLatLon'], INNER_CLOUD_SHIELD_TEMPERATURE)
				
				#if Criteria A and B have been met, then the MCC is initiated, i.e. store node as potentialMCC
		   		if cloudElementAreaB >= INNER_CLOUD_SHIELD_AREA:
		   			#TODO: add another field to the dictionary for the OUTER_AREA_SHIELD area
		   			CounterCriteriaBFlag = True
		   			#append this information on to the dictionary
		   			addInfothisDict(node, cloudElementAreaB, criteriaB)
		   			INITIATIONFLAG = False
		   			MATURITYFLAG = True
		   			stage = 'M'
		   			potentialMCCList = updateMCCList(prunedGraph, potentialMCCList,node,stage, CounterCriteriaAFlag, CounterCriteriaBFlag) 			
	   			else:
	   				#criteria B failed
	   				CounterCriteriaBFlag = False
	   				if INITIATIONFLAG == True:
	   					stage = 'I'   					
	   					potentialMCCList = updateMCCList(prunedGraph, potentialMCCList,node,stage, CounterCriteriaAFlag, CounterCriteriaBFlag)

	   				elif (INITIATIONFLAG == False and MATURITYFLAG == True) or DECAYFLAG==True:
	   					DECAYFLAG = True
	   					MATURITYFLAG = False
	   					stage = 'D'
	   					potentialMCCList = updateMCCList(prunedGraph, potentialMCCList,node,stage, CounterCriteriaAFlag, CounterCriteriaBFlag)
	   		else:
	   			#criteria A failed
	   			CounterCriteriaAFlag = False
	   			CounterCriteriaBFlag = False
	   			#add as a CE before or after the main feature
				if INITIATIONFLAG == True or (INITIATIONFLAG == False and MATURITYFLAG == True):
					stage ="I"
					potentialMCCList = updateMCCList(prunedGraph, potentialMCCList,node,stage, CounterCriteriaAFlag, CounterCriteriaBFlag)
	   			elif (INITIATIONFLAG == False and MATURITYFLAG == False) or DECAYFLAG == True:
	   				stage = "D"
	   				DECAYFLAG = True
	   				potentialMCCList = updateMCCList(prunedGraph, potentialMCCList,node,stage, CounterCriteriaAFlag, CounterCriteriaBFlag)
	   			elif (INITIATIONFLAG == False and MATURITYFLAG == False and DECAYFLAG == False):
	   				stage ="I"
	   				potentialMCCList = updateMCCList(prunedGraph, potentialMCCList,node,stage, CounterCriteriaAFlag, CounterCriteriaBFlag)


   		else:
   			#criteria A failed
   			CounterCriteriaAFlag = False
   			CounterCriteriaBFlag = False
   			#add as a CE before or after the main feature
			if INITIATIONFLAG == True or (INITIATIONFLAG == False and MATURITYFLAG == True):
				stage ="I"
				potentialMCCList = updateMCCList(prunedGraph, potentialMCCList,node,stage, CounterCriteriaAFlag, CounterCriteriaBFlag)
   			elif (INITIATIONFLAG == False and MATURITYFLAG == False) or DECAYFLAG == True:
   				stage = "D"
   				DECAYFLAG = True
   				potentialMCCList = updateMCCList(prunedGraph, potentialMCCList,node,stage, CounterCriteriaAFlag, CounterCriteriaBFlag)
   			elif (INITIATIONFLAG == False and MATURITYFLAG == False and DECAYFLAG == False):
   				stage ="I"
   				potentialMCCList = updateMCCList(prunedGraph, potentialMCCList,node,stage, CounterCriteriaAFlag, CounterCriteriaBFlag)

	return potentialMCCList
#******************************************************************
def updateMCCList(prunedGraph, potentialMCCList,node,stage, CounterCriteriaAFlag, CounterCriteriaBFlag):
	'''
	Purpose:: 
		Utility function to determine if a path is (or is part of) a MCC and provides 
	           preliminary information regarding the stages of the feature

	Input:: 
		prunedGraph: a Networkx Graph representing all the cloud clusters
		potentialMCCList: a list of dictionaries representing the possible MCCs within a path
		node: a string representing the cloud element currently being assessed
		CounterCriteriaAFlag: a boolean value indicating whether the node meets the MCC criteria A according to Laurent et al
		CounterCriteriaBFlag: a boolean value indicating whether the node meets the MCC criteria B according to Laurent et al
	
	Output:: 
		potentialMCCList: list of dictionaries representing all possible MCC within the path
			 dictionary = {"possMCCList":[(node,'I')], "fullMCSMCC":[(node,'I')], "CounterCriteriaA": CounterCriteriaA, "durationAandB": durationAandB}

	'''
	existingFrameFlag = False
	existingMCSFrameFlag = False
	predecessorsFlag = False
	predecessorsMCSFlag = False
	successorsFlag = False
	successorsMCSFlag = False
	frameNum = 0

	frameNum = int((node.split('CE')[0]).split('F')[1])
	if potentialMCCList==[]:
		#list empty
		stage = 'I'
		if CounterCriteriaAFlag == True and CounterCriteriaBFlag ==True:
			potentialMCCList.append({"possMCCList":[(node,stage)], "fullMCSMCC":[(node,stage)], "CounterCriteriaA": 1, "durationAandB": 1, "highestMCCnode":node, "frameNum":frameNum})	
		elif CounterCriteriaAFlag == True and CounterCriteriaBFlag == False:
			potentialMCCList.append({"possMCCList":[], "fullMCSMCC":[(node,stage)], "CounterCriteriaA": 1, "durationAandB": 0, "highestMCCnode":"", "frameNum":0})	
		elif CounterCriteriaAFlag == False and CounterCriteriaBFlag == False:
			potentialMCCList.append({"possMCCList":[], "fullMCSMCC":[(node,stage)], "CounterCriteriaA": 0, "durationAandB": 0, "highestMCCnode":"", "frameNum":0})	

	else:
		#list not empty
		predecessorsFlag, index = isThereALink(prunedGraph, 1,node,potentialMCCList,1)
		
		if predecessorsFlag == True:	

			for eachNode in potentialMCCList[index]["possMCCList"]:
				if int((eachNode[0].split('CE')[0]).split('F')[1]) == frameNum :
					existingFrameFlag = True
					
			#this MUST come after the check for the existing frame
			if CounterCriteriaAFlag == True and CounterCriteriaBFlag ==True:
				stage = 'M'
				potentialMCCList[index]["possMCCList"].append((node,stage))
				potentialMCCList[index]["fullMCSMCC"].append((node,stage))

			
			if existingFrameFlag == False:
				if CounterCriteriaAFlag == True and CounterCriteriaBFlag ==True:
					stage ='M'
					potentialMCCList[index]["CounterCriteriaA"]+= 1
					potentialMCCList[index]["durationAandB"]+=1
					if frameNum > potentialMCCList[index]["frameNum"]:
						potentialMCCList[index]["frameNum"] = frameNum
						potentialMCCList[index]["highestMCCnode"] = node
					return potentialMCCList

				#if this frameNum doesn't exist and this frameNum is less than the MCC node max frame Num (including 0), then append to fullMCSMCC list
				if frameNum > potentialMCCList[index]["frameNum"] or potentialMCCList[index]["frameNum"]==0:
					stage = 'I'
					if CounterCriteriaAFlag == True and CounterCriteriaBFlag == False:
						potentialMCCList.append({"possMCCList":[], "fullMCSMCC":[(node,stage)], "CounterCriteriaA": 1, "durationAandB": 0, "highestMCCnode":"", "frameNum":0})	
						return potentialMCCList
					elif CounterCriteriaAFlag == False and CounterCriteriaBFlag == False:
						potentialMCCList.append({"possMCCList":[], "fullMCSMCC":[(node,stage)], "CounterCriteriaA": 0, "durationAandB": 0, "highestMCCnode":"", "frameNum":0})	
						return potentialMCCList

			#if predecessor and this frame number already exist in the MCC list, add the current node to the fullMCSMCC list
			if existingFrameFlag == True:
				if CounterCriteriaAFlag == True and CounterCriteriaBFlag == False:
					potentialMCCList[index]["fullMCSMCC"].append((node,stage))
					potentialMCCList[index]["CounterCriteriaA"] +=1
					return potentialMCCList
				if CounterCriteriaAFlag == False:
					potentialMCCList[index]["fullMCSMCC"].append((node,stage))	
					return potentialMCCList	
				
		if predecessorsFlag == False:
			successorsFlag, index = isThereALink(prunedGraph, 2,node,potentialMCCList,2)
			
			if successorsFlag == True:
				for eachNode in potentialMCCList[index]["possMCCList"]: 
					if int((eachNode[0].split('CE')[0]).split('F')[1]) == frameNum:
						existingFrameFlag = True
						
				if CounterCriteriaAFlag == True and CounterCriteriaBFlag == True:
					stage = 'M'
					potentialMCCList[index]["possMCCList"].append((node,stage))
					potentialMCCList[index]["fullMCSMCC"].append((node,stage))
					if frameNum > potentialMCCList[index]["frameNum"] or potentialMCCList[index]["frameNum"] == 0:
						potentialMCCList[index]["frameNum"] = frameNum
						potentialMCCList[index]["highestMCCnode"] = node
					return potentialMCCList
		
				
				if existingFrameFlag == False:
					if stage == 'M':
						stage = 'D'
					if CounterCriteriaAFlag == True and CounterCriteriaBFlag ==True:
						potentialMCCList[index]["CounterCriteriaA"]+= 1
						potentialMCCList[index]["durationAandB"]+=1
					elif CounterCriteriaAFlag == True:
						potentialMCCList[index]["CounterCriteriaA"] += 1
					elif CounterCriteriaAFlag == False:
						potentialMCCList[index]["fullMCSMCC"].append((node,stage))
						return potentialMCCList
						#if predecessor and this frame number already exist in the MCC list, add the current node to the fullMCSMCC list
				else:
					if CounterCriteriaAFlag == True and CounterCriteriaBFlag == False:
						potentialMCCList[index]["fullMCSMCC"].append((node,stage))
						potentialMCCList[index]["CounterCriteriaA"] +=1
						return potentialMCCList
					if CounterCriteriaAFlag == False:
						potentialMCCList[index]["fullMCSMCC"].append((node,stage))	
						return potentialMCCList			

		#if this node isn't connected to exisiting MCCs check if it is connected to exisiting MCSs ...
		if predecessorsFlag == False and successorsFlag == False:
			stage = 'I'
			predecessorsMCSFlag, index = isThereALink(prunedGraph, 1,node,potentialMCCList,2)
			if predecessorsMCSFlag == True:
				if CounterCriteriaAFlag == True and CounterCriteriaBFlag == True:
					potentialMCCList[index]["possMCCList"].append((node,'M'))
					potentialMCCList[index]["fullMCSMCC"].append((node,'M'))
					potentialMCCList[index]["durationAandB"] += 1
					if frameNum > potentialMCCList[index]["frameNum"]:
						potentialMCCList[index]["frameNum"] = frameNum
						potentialMCCList[index]["highestMCCnode"] = node
					return potentialMCCList

				if potentialMCCList[index]["frameNum"] == 0 or frameNum <= potentialMCCList[index]["frameNum"]:
					if CounterCriteriaAFlag == True and CounterCriteriaBFlag == False:
						potentialMCCList[index]["fullMCSMCC"].append((node,stage))
						potentialMCCList[index]["CounterCriteriaA"] +=1
						return potentialMCCList
					elif CounterCriteriaAFlag == False:
						potentialMCCList[index]["fullMCSMCC"].append((node,stage))
						return potentialMCCList
			else:
				successorsMCSFlag, index = isThereALink(prunedGraph, 2,node,potentialMCCList,2)
				if successorsMCSFlag == True:
					if CounterCriteriaAFlag == True and CounterCriteriaBFlag == True:
						potentialMCCList[index]["possMCCList"].append((node,'M'))
						potentialMCCList[index]["fullMCSMCC"].append((node,'M'))
						potentialMCCList[index]["durationAandB"] += 1
						if frameNum > potentialMCCList[index]["frameNum"]:
							potentialMCCList[index]["frameNum"] = frameNum
							potentialMCCList[index]["highestMCCnode"] = node
						return potentialMCCList

					
					if potentialMCCList[index]["frameNum"] == 0 or frameNum <= potentialMCCList[index]["frameNum"]:
						if CounterCriteriaAFlag == True and CounterCriteriaBFlag == False:
							potentialMCCList[index]["fullMCSMCC"].append((node,stage))
							potentialMCCList[index]["CounterCriteriaA"] +=1
							return potentialMCCList
						elif CounterCriteriaAFlag == False:
							potentialMCCList[index]["fullMCSMCC"].append((node,stage))
							return potentialMCCList
					
			#if this node isn't connected to existing MCCs or MCSs, create a new one ...
			if predecessorsFlag == False and predecessorsMCSFlag == False and successorsFlag == False and successorsMCSFlag == False:	
				if CounterCriteriaAFlag == True and CounterCriteriaBFlag ==True:
					potentialMCCList.append({"possMCCList":[(node,stage)], "fullMCSMCC":[(node,stage)], "CounterCriteriaA": 1, "durationAandB": 1, "highestMCCnode":node, "frameNum":frameNum})	
				elif CounterCriteriaAFlag == True and CounterCriteriaBFlag == False:
					potentialMCCList.append({"possMCCList":[], "fullMCSMCC":[(node,stage)], "CounterCriteriaA": 1, "durationAandB": 0, "highestMCCnode":"", "frameNum":0})	
				elif CounterCriteriaAFlag == False and CounterCriteriaBFlag == False:
					potentialMCCList.append({"possMCCList":[], "fullMCSMCC":[(node,stage)], "CounterCriteriaA": 0, "durationAandB": 0, "highestMCCnode":"", "frameNum":0})	

	return potentialMCCList
#******************************************************************
def isThereALink(prunedGraph, upOrDown,node,potentialMCCList,whichList):
	'''
	Purpose:: 
		Utility script for updateMCCList mostly because there is no Pythonic way to break out of nested loops
	
	Input:: 
		prunedGraph:a Networkx Graph representing all the cloud clusters
		upOrDown: an integer representing 1- to do predecesor check and 2 - to do successor checkedNodesMCC
		node: a string representing the cloud element currently being assessed
		potentialMCCList: a list of dictionaries representing the possible MCCs within a path
		whichList: an integer representing which list ot check in the dictionary; 1- possMCCList, 2- fullMCSMCC
			
	Output:: 
		thisFlag: a boolean representing whether the list passed has in the parent or child of the node
		index: an integer representing the location in the potentialMCCList where thisFlag occurs

	'''
	thisFlag = False
	index = -1
	checkList =""
	if whichList == 1:
		checkList = "possMCCList"
	elif whichList ==2:
		checkList = "fullMCSMCC"

	#check parents
	if upOrDown == 1:
		for aNode in prunedGraph.predecessors(node):
			#reset the index counter for this node search through potentialMCCList
			index = -1
			for MCCDict in potentialMCCList:
				index += 1
				if aNode in list(x[0] for x in MCCDict[checkList]): 
					thisFlag = True
					#get out of looping so as to avoid the flag being written over when another node in the predecesor list is checked
					return thisFlag, index

	#check children
	if upOrDown == 2:
		for aNode in prunedGraph.successors(node):
			#reset the index counter for this node search through potentialMCCList
			index = -1
			for MCCDict in potentialMCCList:
				index += 1
				
				if aNode in list(x[0] for x in MCCDict[checkList]): 
					thisFlag = True
					return thisFlag, index

	return thisFlag, index
#******************************************************************
def maxExtentAndEccentricity(eachList):
	'''
	Purpose:: 
		Perform the final check for MCC based on maximum extent and eccentricity criteria

	Input:: 
		eachList: a list of strings  representing the node of the possible MCCs within a path

	Output:: 
		maxShieldNode: a string representing the node with the maximum maxShieldNode
	    definiteMCCFlag: a boolean indicating that the MCC has met all requirements

	'''
	maxShieldNode =''
	maxShieldArea = 0.0
	maxShieldEccentricity = 0.0
	definiteMCCFlag = False
	
	if eachList:
		for eachNode in eachList:
			if (thisDict(eachNode)['nodeMCSIdentifier'] == 'M' or thisDict(eachNode)['nodeMCSIdentifier'] == 'D') and thisDict(eachNode)['cloudElementArea'] > maxShieldArea:
				maxShieldNode = eachNode
				maxShieldArea = thisDict(eachNode)['cloudElementArea']
				
		maxShieldEccentricity = thisDict(maxShieldNode)['cloudElementEccentricity']
		if thisDict(maxShieldNode)['cloudElementEccentricity'] >= ECCENTRICITY_THRESHOLD_MIN and thisDict(maxShieldNode)['cloudElementEccentricity'] <= ECCENTRICITY_THRESHOLD_MAX :
			#criteria met
			definiteMCCFlag = True
			
	return maxShieldNode, definiteMCCFlag		
#******************************************************************
def findMaxDepthAndMinPath (thisPathDistanceAndLength):
	'''
	Purpose:: 
		To determine the maximum depth and min path for the headnode

	Input:: 
		tuple of dictionaries representing the shortest distance and paths for a node in the tree as returned by nx.single_source_dijkstra
		thisPathDistanceAndLength({distance}, {path})
			{distance} = nodeAsString, valueAsInt, {path} = nodeAsString, pathAsList

	Output:: 
		tuple of the max pathLength and min pathDistance as a tuple (like what was input)
			minDistanceAndMaxPath = ({distance},{path}) 
	'''
	maxPathLength = 0
	minPath = 0

	#maxPathLength for the node in question
	maxPathLength = max(len (values) for values in thisPathDistanceAndLength[1].values())

	#if the duration is shorter then the min MCS length, then don't store!
	if maxPathLength < MIN_MCS_DURATION: #MINIMUM_DURATION :
		minDistanceAndMaxPath = ()

	#else find the min path and max depth
	else:
		#max path distance for the node in question  
		minPath = max(values for values in thisPathDistanceAndLength[0].values())
		
		#check to determine the shortest path from the longest paths returned
		for pathDistance, path in itertools.izip(thisPathDistanceAndLength[0].values(), thisPathDistanceAndLength[1].values()):
			pathLength = len(path)
			#if pathLength is the same as the maxPathLength, then look the pathDistance to determine if the min
			if pathLength == maxPathLength :
				if pathDistance <= minPath:
					minPath = pathLength
					#store details if absolute minPath and deepest
					minDistanceAndMaxPath = (pathDistance, path)
	return minDistanceAndMaxPath
#******************************************************************
def thisDict (thisNode):
	'''
	Purpose:: 
		Return dictionary from graph if node exist in tree

	Input:: 
		thisNode: a string representing the CE to get the information for

	Output :: 
		eachdict[1]: a dictionary representing the info associated with thisNode from the graph

	'''
	for eachdict in CLOUD_ELEMENT_GRAPH.nodes(thisNode):
		if eachdict[1]['uniqueID'] == thisNode:
			return eachdict[1]
#******************************************************************
def checkCriteria (thisCloudElementLatLon, aTemperature):
	'''
	Purpose:: 
		Determine if criteria B is met for a CEGraph

	Input:: 
		thisCloudElementLatLon: 2D array of (lat,lon) variable from the node dictionary being currently considered
		aTemperature:a integer representing the temperature maximum for masking

	Output :: 
		cloudElementArea: a floating-point number representing the area in the array that meet the criteria - criteriaB

	'''
	cloudElementCriteriaBLatLon=[]

	frame, CEcounter = ndimage.measurements.label(thisCloudElementLatLon, structure=STRUCTURING_ELEMENT)
	frameCEcounter=0
	#determine min and max values in lat and lon, then use this to generate teh array from LAT,LON meshgrid
	
	minLat = min(x[0] for x in thisCloudElementLatLon)
	maxLat = max(x[0]for x in thisCloudElementLatLon)
	minLon = min(x[1]for x in thisCloudElementLatLon)
	maxLon = max(x[1]for x in thisCloudElementLatLon)

	minLatIndex = np.argmax(LAT[:,0] == minLat)
	maxLatIndex = np.argmax(LAT[:,0]== maxLat)
	minLonIndex = np.argmax(LON[0,:] == minLon)
	maxLonIndex = np.argmax(LON[0,:] == maxLon)

	criteriaBframe = ma.zeros(((abs(maxLatIndex - minLatIndex)+1), (abs(maxLonIndex - minLonIndex)+1)))
	
	for x in thisCloudElementLatLon:
		#to store the values of the subset in the new array, remove the minLatIndex and minLonindex from the
		#index given in the original array to get the indices for the new array
		criteriaBframe[(np.argmax(LAT[:,0] == x[0]) - minLatIndex),(np.argmax(LON[0,:] == x[1]) - minLonIndex)] = x[2]

	#keep only those values < aTemperature
	tempMask = ma.masked_array(criteriaBframe, mask=(criteriaBframe >= aTemperature), fill_value = 0)
	
	#get the actual values that the mask returned
	criteriaB = ma.zeros((criteriaBframe.shape)).astype('int16')
	
	for index, value in maenumerate(tempMask): 
		lat_index, lon_index = index			
		criteriaB[lat_index, lon_index]=value	

   	for count in xrange(CEcounter):
   		#[0] is time dimension. Determine the actual values from the data
   		#loc is a masked array
   		#***** returns elements down then across thus (6,4) is 6 arrays deep of size 4
   		try:

	   		loc = ndimage.find_objects(criteriaB)[0]
	   	except:
	   		#this would mean that no objects were found meeting criteria B
	   		print "no objects at this temperature!"
	   		cloudElementArea = 0.0
	   		return cloudElementArea, cloudElementCriteriaBLatLon
	   
	   	try:
	   		cloudElementCriteriaB = ma.zeros((criteriaB.shape))
	   		cloudElementCriteriaB =criteriaB[loc] 
	   	except:
	   		print "YIKESS"
	   		print "CEcounter ", CEcounter, criteriaB.shape
	   		print "criteriaB ", criteriaB

   		for index,value in np.ndenumerate(cloudElementCriteriaB):
   			if value !=0:
   				t,lat,lon = index
   				#add back on the minLatIndex and minLonIndex to find the true lat, lon values
   				lat_lon_tuple = (LAT[(lat),0], LON[0,(lon)],value)
   				cloudElementCriteriaBLatLon.append(lat_lon_tuple)

		cloudElementArea = np.count_nonzero(cloudElementCriteriaB)*XRES*YRES
		#do some cleaning up
		tempMask =[]
		criteriaB =[]
		cloudElementCriteriaB=[]

		return cloudElementArea, cloudElementCriteriaBLatLon
#******************************************************************
def hasMergesOrSplits (nodeList):
	'''
	Purpose:: 
		Determine if nodes within a path defined from shortest_path splittingNodeDict
	Input:: 
		nodeList: list of strings representing the nodes from a path
	Output:: 
		splitList: a list of strings representing all the nodes in the path that split
		mergeList: a list of strings representing all the nodes in the path that merged
	'''
	mergeList=[]
	splitList=[]

	for node,numParents in PRUNED_GRAPH.in_degree(nodeList).items():
		if numParents > 1:
			mergeList.append(node)

	for node, numChildren in PRUNED_GRAPH.out_degree(nodeList).items():
		if numChildren > 1:
			splitList.append(node)
	#sort
	splitList.sort(key=lambda item:(len(item.split('C')[0]), item.split('C')[0]))
	mergeList.sort(key=lambda item:(len(item.split('C')[0]), item.split('C')[0]))
			
	return mergeList,splitList
#******************************************************************
def allAncestors(path, aNode):
	'''
	Purpose:: 
		Utility script to provide the path leading up to a nodeList

	Input:: 
		path: a list of strings representing the nodes in the path 
	    aNode: a string representing a node to be checked for parents

	Output:: 
		path: a list of strings representing the list of the nodes connected to aNode through its parents
		numOfChildren: an integer representing the number of parents of the node passed
	'''

	numOfParents = PRUNED_GRAPH.in_degree(aNode)
	try:
		if PRUNED_GRAPH.predecessors(aNode) and numOfParents <= 1:
			path = path + PRUNED_GRAPH.predecessors(aNode)
			thisNode = PRUNED_GRAPH.predecessors(aNode)[0]
			return allAncestors(path,thisNode)
		else:
			path = path+aNode
			return path, numOfParents
	except:
		return path, numOfParents
#******************************************************************
def allDescendants(path, aNode):
	'''
	Purpose:: 
		Utility script to provide the path leading up to a nodeList

	Input:: 
		path: a list of strings representing the nodes in the path 
	    aNode: a string representing a node to be checked for children

	Output:: 
		path: a list of strings representing the list of the nodes connected to aNode through its children
		numOfChildren: an integer representing the number of children of the node passed
	'''

	numOfChildren = PRUNED_GRAPH.out_degree(aNode)
	try:
		if PRUNED_GRAPH.successors(aNode) and numOfChildren <= 1:
			path = path + PRUNED_GRAPH.successors(aNode)
			thisNode = PRUNED_GRAPH.successors(aNode)[0]
			return allDescendants(path,thisNode)
		else:
			path = path + aNode
			#i.e. PRUNED_GRAPH.predecessors(aNode) is empty
			return path, numOfChildren
	except:
		#i.e. PRUNED_GRAPH.predecessors(aNode) threw an exception
		return path, numOfChildren
#******************************************************************
def addInfothisDict (thisNode, cloudElementArea,criteriaB):
	'''
	Purpose:: 
		Update original dictionary node with information

	Input:: 
		thisNode: a string representing the unique ID of a node
		cloudElementArea: a floating-point number representing the area of the cloud element
		criteriaB: a masked array of floating-point numbers representing the lat,lons meeting the criteria  

	Output:: None 

	'''
	for eachdict in CLOUD_ELEMENT_GRAPH.nodes(thisNode):
		if eachdict[1]['uniqueID'] == thisNode:
			eachdict[1]['CriteriaBArea'] = cloudElementArea
			eachdict[1]['CriteriaBLatLon'] = criteriaB
	return
#******************************************************************
def addNodeBehaviorIdentifier (thisNode, nodeBehaviorIdentifier):
	'''
	Purpose:: add an identifier to the node dictionary to indicate splitting, merging or neither node

	Input:: 
		thisNode: a string representing the unique ID of a node
	    nodeBehaviorIdentifier: a string representing the behavior S- split, M- merge, B- both split and merge, N- neither split or merge 

	Output :: None

	'''
	for eachdict in CLOUD_ELEMENT_GRAPH.nodes(thisNode):
		if eachdict[1]['uniqueID'] == thisNode:
			if not 'nodeBehaviorIdentifier' in eachdict[1].keys():
				eachdict[1]['nodeBehaviorIdentifier'] = nodeBehaviorIdentifier
	return
#******************************************************************
def addNodeMCSIdentifier (thisNode, nodeMCSIdentifier):
	'''
	Purpose:: 
		Add an identifier to the node dictionary to indicate splitting, merging or neither node

	Input:: 
		thisNode: a string representing the unique ID of a node
		nodeMCSIdentifier: a string representing the stage of the MCS lifecyle  'I' for Initiation, 'M' for Maturity, 'D' for Decay

	Output :: None

	'''
	for eachdict in CLOUD_ELEMENT_GRAPH.nodes(thisNode):
		if eachdict[1]['uniqueID'] == thisNode:
			if not 'nodeMCSIdentifier' in eachdict[1].keys():
				eachdict[1]['nodeMCSIdentifier'] = nodeMCSIdentifier
	return
#******************************************************************
# def updateNodeMCSIdentifier (thisNode, nodeMCSIdentifier):
# 	'''
# 	Purpose:: 
# 		Update an identifier to the node dictionary to indicate splitting, merging or neither node

# 	Input:: 
# 		thisNode: thisNode: a string representing the unique ID of a node
# 		nodeMCSIdentifier: a string representing the stage of the MCS lifecyle  'I' for Initiation, 'M' for Maturity, 'D' for Decay  

# 	Output :: None

# 	'''
# 	for eachdict in CLOUD_ELEMENT_GRAPH.nodes(thisNode):
# 		if eachdict[1]['uniqueID'] == thisNode:
# 			eachdict[1]['nodeMCSIdentifier'] = nodeBehaviorIdentifier

# 	return
# #******************************************************************
def eccentricity (cloudElementLatLon):
	'''
	Purpose::
	    Determines the eccentricity (shape) of contiguous boxes 
	    Values tending to 1 are more circular by definition, whereas 
	    values tending to 0 are more linear
	
	Input::
		cloudElementLatLon: 2D array in (lat,lon) representing T_bb contiguous squares 
		
	Output::
		epsilon: a floating-point representing the eccentricity of the matrix passed
	
	'''
	
	epsilon = 0.0
	
	#loop over all lons and determine longest (non-zero) col
	#loop over all lats and determine longest (non-zero) row
	for latLon in cloudElementLatLon:
	    #assign a matrix to determine the legit values
	    
	    nonEmptyLons = sum(sum(cloudElementLatLon)>0)
        nonEmptyLats = sum(sum(cloudElementLatLon.transpose())>0)
        
        lonEigenvalues = 1.0 * nonEmptyLats / (nonEmptyLons+0.001) #for long oval on y axis
        latEigenvalues = 1.0 * nonEmptyLons / (nonEmptyLats +0.001) #for long oval on x-axs
        epsilon = min(latEigenvalues,lonEigenvalues)
        
	return epsilon
#******************************************************************
def cloudElementOverlap (currentCELatLons, previousCELatLons):
	'''
	Purpose::
	    Determines the percentage overlap between two list of lat-lons passed

	Input::
	    currentCELatLons: a list of tuples for the current CE
	    previousCELatLons: a list of tuples for the other CE being considered

	Output::
	    percentageOverlap: a floating-point representing the number of overlapping lat_lon tuples
	    areaOverlap: a floating-point number representing the area overlapping

	'''

	latlonprev =[]
	latloncurr = []
	count = 0 
	percentageOverlap = 0.0
	areaOverlap = 0.0

	#remove the temperature from the tuples for currentCELatLons and previousCELatLons then check for overlap
	latlonprev = [(x[0],x[1]) for x in previousCELatLons]
	latloncurr = [(x[0],x[1]) for x in currentCELatLons]  

	#find overlap
	count = len(list(set(latloncurr)&set(latlonprev)))

	#find area overlap
	areaOverlap = count*XRES*YRES
	
	#find percentage
	percentageOverlap = max(((count*1.0)/(len(latloncurr)*1.0)),((count*1.0)/(len(latlonprev)*1.0)))
	
	return percentageOverlap, areaOverlap
#******************************************************************
def findCESpeed(node, MCSList):
	'''
	Purpose:: 
		To determine the speed of the CEs uses vector displacement delta_lat/delta_lon (y/x)

	Input:: 
		node: a string representing the CE
		MCSList: a list of strings representing the feature

	Output::
		CEspeed: a floating-point number representing the speed of the CE 

	'''

	delta_lon =0.0
	delta_lat =0.0
	CEspeed =[]
	theSpeed = 0.0
	

	theList = CLOUD_ELEMENT_GRAPH.successors(node)
	nodeLatLon=thisDict(node)['cloudElementCenter']

	
	for aNode in theList:
		if aNode in MCSList:
			#if aNode is part of the MCSList then determine distance
			aNodeLatLon = thisDict(aNode)['cloudElementCenter']
			#calculate CE speed
			#checking the lats
			# nodeLatLon[0] += 90.0
			# aNodeLatLon[0] += 90.0
			# delta_lat = (nodeLatLon[0] - aNodeLatLon[0]) 
			delta_lat = ((thisDict(node)['cloudElementCenter'][0] +90.0) - (thisDict(aNode)['cloudElementCenter'][0]+90.0))
			# nodeLatLon[1] += 360.0
			# aNodeLatLon[1] += 360.0
			# delta_lon = (nodeLatLon[1] - aNodeLatLon[1]) 
			delta_lon = ((thisDict(node)['cloudElementCenter'][1]+360.0) - (thisDict(aNode)['cloudElementCenter'][1]+360.0))
			
			#failsafe for movement only in one dir
			if delta_lat == 0.0:
				delta_lat = 1.0

			if delta_lon == 0.0:
				delta_lon = 1.0

			try:
				theSpeed = abs((((delta_lat/delta_lon)*LAT_DISTANCE*1000)/(TRES*3600))) #convert to s --> m/s
			except:
				theSpeed = 0.0
			
			CEspeed.append(theSpeed)

			# print "~~~ ", thisDict(aNode)['uniqueID']
			# print "*** ", nodeLatLon, thisDict(node)['cloudElementCenter']
			# print "*** ", aNodeLatLon, thisDict(aNode)['cloudElementCenter']
			
	if not CEspeed:
		return 0.0
	else:
		return min(CEspeed)	
#******************************************************************
#
#			UTILITY SCRIPTS FOR MCCSEARCH.PY
#
#******************************************************************
def maenumerate(mArray):
	'''
	Purpose::
	    Utility script for returning the actual values from the masked array
	    Taken from: http://stackoverflow.com/questions/8620798/numpy-ndenumerate-for-masked-arrays
	
	Input::
		mArray: the masked array returned from the ma.array() command
		
		
	Output::
		maskedValues: 3D (t,lat,lon), value of only masked values
	
	'''

	mask = ~mArray.mask.ravel()
	#beware yield fast, but generates a type called "generate" that does not allow for array methods
	for index, maskedValue in itertools.izip(np.ndenumerate(mArray), mask):
	    if maskedValue: 
			yield index	
#******************************************************************
def bbox2ij(lon,lat,bbox):
    '''
    Purpose:: Return indices for i,j that will completely cover the specified bounding box.     
    i0,i1,j0,j1 = bbox2ij(lon,lat,bbox)
    
    Inputs:: lon,lat: = 2D arrays that are the target of the subset
    		  bbox: list containing the bounding box: [lon_min, lon_max, lat_min, lat_max]
    
    Outputs::


    Adapted from: http://gis.stackexchange.com/questions/71630/subsetting-a-curvilinear-netcdf-file-roms-model-output-using-a-lon-lat-boundin

    Example
    -------  
    >>> i0,i1,j0,j1 = bbox2ij(lon_rho,[-71, -63., 39., 46])
    >>> h_subset = nc.variables['h'][j0:j1,i0:i1]       
    '''

    bbox=np.array(bbox)
    mypath=np.array([bbox[[0,1,1,0]],bbox[[2,2,3,3]]]).T
    p = path.Path(mypath)
    points = np.vstack((lon.flatten(),lat.flatten())).T   
    n,m = np.shape(lon)
    inside = p.contains_points(points).reshape((n,m))
    ii,jj = np.meshgrid(xrange(m),xrange(n))
    return min(ii[inside]),max(ii[inside]),min(jj[inside]),max(jj[inside])
#******************************************************************
def getModelTimes(modelFile, timeVarName):
    '''
    Taken from the original RCMES 

    TODO:  Do a better job handling dates here
    Purpose:: Routine to convert from model times ('hours since 1900...', 'days since ...')
    into a python datetime structure

    Input::
        modelFile - path to the model tile you want to extract the times list and modelTimeStep from
        timeVarName - name of the time variable in the model file

    Output::
        times  - list of python datetime objects describing model data times
        modelTimeStep - 'hourly','daily','monthly','annual'
    '''

    f = Dataset(modelFile,'r', format='NETCDF')
    xtimes = f.variables[timeVarName]
    timeFormat = xtimes.units #attributes['units']
    
    # search to check if 'since' appears in units
    try:
         sinceLoc = re.search('since', timeFormat).end()


    #KDW the below block generates and error. But the print statement, indicates that sinceLoc found something
    except AttributeError:
         print 'Error decoding model times: time variable attributes do not contain "since"'
         raise

    units = ''
    TIME_UNITS = ('minutes', 'hours', 'days', 'months', 'years')
    # search for 'seconds','minutes','hours', 'days', 'months', 'years' so know units
    for unit in TIME_UNITS:
        if re.search(unit, timeFormat):
            units = unit
            break

    # cut out base time (the bit following 'since')
    base_time_string = string.lstrip(timeFormat[sinceLoc:])
    
    # decode base time
    base_time = decodeTimeFromString(base_time_string)
    
    times = []

    print "**** ", timeFormat
    print units

    xtime = int(timeFormat[-2:])
    
    for xtime in xtimes[:]:         
        # Cast time as an int ***KDW remove this so fractional xtime can be read from MERG
        xtime = int(xtime)

        if units == 'minutes':
            dt = datetime.timedelta(minutes=xtime)
            new_time = base_time + dt
        elif units == 'hours':
            dt = datetime.timedelta(hours=xtime)
            new_time = base_time + dt
        elif units == 'days':
            dt = datetime.timedelta(days=xtime)
            new_time = base_time + dt
        elif units == 'months':
            # NB. adding months in python is complicated as month length varies and hence ambiguous.
            # Perform date arithmatic manually
            #  Assumption: the base_date will usually be the first of the month
            #              NB. this method will fail if the base time is on the 29th or higher day of month
            #                      -as can't have, e.g. Feb 31st.
            new_month = int(base_time.month + xtime % 12)
            new_year = int(math.floor(base_time.year + xtime / 12.))
            new_time = datetime.datetime(new_year, new_month, base_time.day, base_time.hour, base_time.second, 0)
        elif units == 'years':
            dt = datetime.timedelta(years=xtime)
            new_time = base_time + dt
        
        #print "xtime is:", xtime, "dt is: ", dt
        
        times.append(new_time)
       
    try:
        timeStepLength = int(xtimes[1] - xtimes[0] + 1.e-12)
        modelTimeStep = getModelTimeStep(units, timeStepLength)
     
        #KDW if timeStepLength is zero do not normalize times as this would create an empty list
        if timeStepLength != 0:
          times = normalizeDatetimes(times, modelTimeStep) 
    except:
        raise

    return times, modelTimeStep
#******************************************************************    
def getModelTimeStep(units, stepSize):
    # Time units are now determined. Determine the time intervals of input data (mdlTimeStep)

    if units == 'minutes':
        if stepSize == 60:
            modelTimeStep = 'hourly'
        elif stepSize == 1440:
            modelTimeStep = 'daily'
        # 28 days through 31 days
        elif 40320 <= stepSize <= 44640:
            modelTimeStep = 'monthly'
        # 365 days through 366 days 
        elif 525600 <= stepSize <= 527040:
            modelTimeStep = 'annual' 
        else:
            raise Exception('model data time step interval exceeds the max time interval (annual)', units, stepSize)

    elif units == 'hours':
      #need a check for fractional hrs and only one hr i.e. stepSize=0
        if stepSize == 0 or stepSize == 1:
            modelTimeStep = 'hourly'
        elif stepSize == 24:
            modelTimeStep = 'daily'
        elif 672 <= stepSize <= 744:
            modelTimeStep = 'monthly' 
        elif 8760 <= stepSize <= 8784:
            modelTimeStep = 'annual' 
        else:
            raise Exception('model data time step interval exceeds the max time interval (annual)', units, stepSize)

    elif units == 'days':
        if stepSize == 1:
            modelTimeStep = 'daily'
        elif 28 <= stepSize <= 31:
            modelTimeStep = 'monthly'
        elif 365 <= stepSize <= 366:
            modelTimeStep = 'annual'
        else:
            raise Exception('model data time step interval exceeds the max time interval (annual)', units, stepSize)

    elif units == 'months':
        if stepSize == 1:
            modelTimeStep = 'monthly'
        elif stepSize == 12:
            modelTimeStep = 'annual'
        else:
            raise Exception('model data time step interval exceeds the max time interval (annual)', units, stepSize)

    elif units == 'years':
        if stepSize == 1:
            modelTimeStep = 'annual'
        else:
            raise Exception('model data time step interval exceeds the max time interval (annual)', units, stepSize)

    else:
        errorMessage = 'the time unit ', units, ' is not currently handled in this version.'
        raise Exception(errorMessage)

    return modelTimeStep
#******************************************************************    
def createMainDirectory(mainDirStr):
	'''
	Purpose:: 
		To create the main directory for storing information and
		the subdirectories for storing information
	Input:: 
		mainDir: a directory for where all information generated from
			the program are to be stored
	Output:: None

	'''
	global MAINDIRECTORY

	MAINDIRECTORY = mainDirStr
	#if directory doesnt exist, creat it
	if not os.path.exists(MAINDIRECTORY):
		os.makedirs(MAINDIRECTORY)

	os.chdir((MAINDIRECTORY))
	#create the subdirectories
	try:	
		os.makedirs('images')
		os.makedirs('textFiles')
		os.makedirs('MERGnetcdfCEs')
		os.makedirs('TRMMnetcdfCEs')
	except:
		print "Directory exists already!!!"
		#TODO: some nice way of prompting if it is ok to continue...or just leave

	return 
#******************************************************************
def checkForFiles(startTime, endTime, thisDir, fileType):
	'''
	Purpose:: To ensure all the files between the starttime and endTime
			  exist in the directory supplied

	Input:: 
			startTime: a string yyyymmmddhh representing the starttime 
			endTime: a string yyyymmmddhh representing the endTime
			thisDir: a string representing the directory path where to 
				look for the file
			fileType: an integer representing the type of file in the directory
				1 - MERG original files, 2 - TRMM original files

	Output:: 
			status: a boolean representing whether all files exists

	'''
	filelist =[]
	startFilename = ''
	endFilename =''
	currFilename = ''
	status = False
	startyr = int(startTime[:4])
	startmm = int(startTime[4:6])
	startdd = int(startTime[6:8])
	starthr = int(startTime[-2:])
	endyr = int(endTime[:4])
	endmm = int(endTime[4:6])
	enddd = int(endTime[6:8])
	endhh = int(endTime[-2:])
	curryr = startyr
	currmm = startmm
	currdd = startdd
	currhr = starthr
	currmmStr = ''
	currddStr = ''
	currhrStr = ''
	endmmStr = ''
	endddStr =''
	endhhStr = ''

	#check that the startTime is before the endTime
	if fileType == 1:
		#print "fileType is 1"
		startFilename = "merg_"+startTime+"_4km-pixel.nc"
		endFilename = thisDir+"/merg_"+endTime+"_4km-pixel.nc"

	if fileType == 2:
		#TODO:: determine closest time for TRMM files for end 
		#http://disc.sci.gsfc.nasa.gov/additional/faq/precipitation_faq.shtml#convert
		#How do I extract time information from the TRMM 3B42 file name? section
		# startFilename = "3B42."+startTime[:8]+"."+currhr+".7A.nc"
		# endFilename = "3B42."+endTime[:8]+"."+endTime[-2:]+".7A.nc"
		if starthr%3 == 2:
			currhr += 1	
		elif starthr%3 ==1:
			currhr -= 1
		else:
			currhr = starthr

		curryr, currmmStr, currddStr, currhrStr,_,_,_ = findTime(curryr, currmm, currdd, currhr)

		startFilename = "3B42."+str(curryr)+currmmStr+currddStr+"."+currhrStr+".7A.nc"	
		if endhh%3 == 2:
			endhh += 1
		elif endhh%3 ==1:
			endhh -= 1

		endyr, endmmStr, endddStr, endhhStr, _, _, _ = findTime(endyr, endmm, enddd, endhh)

		endFilename = thisDir+"/3B42."+str(endyr)+endmmStr+endddStr+"."+endhhStr+".7A.nc"

	#check for files between startTime and endTime
	currFilename = thisDir+"/"+startFilename

	while currFilename is not endFilename:

		if not os.path.isfile(currFilename):
			print "file is missing! Filename: ", currFilename
			status = False
			return status, filelist
		else:
			#create filelist
			filelist.append(currFilename)
	
		status = True
		if currFilename == endFilename:
			break

		#generate new currFilename
		if fileType == 1:
			currhr +=1
		elif fileType ==2:
			currhr += 3

		curryr, currmmStr, currddStr, currhrStr, currmm, currdd, currhr = findTime(curryr, currmm, currdd, currhr)

		if fileType == 1:
			currFilename = thisDir+"/"+"merg_"+str(curryr)+currmmStr+currddStr+currhrStr+"_4km-pixel.nc"
		if fileType == 2:
			currFilename = thisDir+"/"+"3B42."+str(curryr)+currmmStr+currddStr+"."+currhrStr+".7A.nc"

	return status,filelist
#******************************************************************
def findTime(curryr, currmm, currdd, currhr):
	'''
	Purpose:: To determine the new yr, mm, dd, hr

	Input:: curryr, an integer representing the year
			currmm, an integer representing the month
			currdd, an integer representing the day
			currhr, an integer representing the hour

	Output::curryr, an integer representing the year
			currmm, an integer representing the month
			currdd, an integer representing the day
			currhr, an integer representing the hour
	'''
	if currhr > 23:
		currhr = 0
		currdd += 1
		if currdd > 30 and (currmm == 4 or currmm == 6 or currmm == 9 or currmm == 11):
			currmm +=1
			currdd = 1
		elif currdd > 31 and (currmm == 1 or currmm ==3 or currmm == 5 or currmm == 7 or currmm == 8 or currmm == 10):
			currmm +=1
			currdd = 1
		elif currdd > 31 and currmm == 12:
			currmm = 1
			currdd = 1
			curryr += 1
		elif currdd > 28 and currmm == 2 and (curryr%4)!=0:
			currmm = 3
			currdd = 1
		elif (curryr%4)==0 and currmm == 2 and currdd>29:
			currmm = 3
			currdd = 1

	if currmm < 10:
		currmmStr="0"+str(currmm)
	else:
		currmmStr = str(currmm)

	if currdd < 10:
		currddStr = "0"+str(currdd)
	else:
		currddStr = str(currdd)

	if currhr < 10:
		currhrStr = "0"+str(currhr)
	else:
		currhrStr = str(currhr)

	return curryr, currmmStr, currddStr, currhrStr, currmm, currdd, currhr
#******************************************************************	
def find_nearest(thisArray,value):
	'''
	Purpose :: to determine the value within an array closes to 
			another value

	Input ::
	Output::
	'''
	idx = (np.abs(thisArray-value)).argmin()
	return thisArray[idx]
#******************************************************************	
def preprocessingMERG(MERGdirname):
	'''
	Purpose::
	    Utility script for unzipping and converting the merg*.Z files from Mirador to 
	    NETCDF format. The files end up in a folder called mergNETCDF in the directory
	    where the raw MERG data is
	    NOTE: VERY RAW AND DIRTY 

	Input::
	    Directory to the location of the raw MERG files, preferably zipped
		
	Output::
	   none

	Assumptions::
	   1 GrADS (http://www.iges.org/grads/gadoc/) and lats4D (http://opengrads.org/doc/scripts/lats4d/)
	     have been installed on the system and the user can access 
	   2 User can write files in location where script is being called
	   3 the files havent been unzipped	
	'''

	os.chdir((MERGdirname+'/'))
	imgFilename = ''

	#Just incase the X11 server is giving problems
	subprocess.call('export DISPLAY=:0.0', shell=True)

	for files in glob.glob("*-pixel"):
	#for files in glob.glob("*.Z"):
		fname = os.path.splitext(files)[0]

		#unzip it
		bash_cmd = 'gunzip ' + files
		subprocess.call(bash_cmd, shell=True)

		#determine the time from the filename
		ftime = re.search('\_(.*)\_',fname).group(1)

		yy = ftime[0:4]
		mm = ftime[4:6]
		day = ftime[6:8]
		hr = ftime [8:10]

		#TODO: must be something more efficient!

		if mm=='01':
			mth = 'Jan'
		if mm == '02':
			mth = 'Feb'
		if mm == '03':
			mth = 'Mar'
		if mm == '04':
			mth = 'Apr'
		if mm == '05':
			mth = 'May'
		if mm == '06':
			mth = 'Jun'
		if mm == '07':
			mth = 'Jul'
		if mm == '08':
			mth = 'Aug'
		if mm == '09':
			mth = 'Sep'
		if mm == '10':
			mth = 'Oct'
		if mm == '11':
			mth = 'Nov'
		if mm == '12':
			mth = 'Dec'


		subprocess.call('rm merg.ctl', shell=True)
		subprocess.call('touch merg.ctl', shell=True)
		replaceExpDset = 'echo DSET ' + fname +' >> merg.ctl'
		replaceExpTdef = 'echo TDEF 99999 LINEAR '+hr+'z'+day+mth+yy +' 30mn' +' >> merg.ctl'
		subprocess.call(replaceExpDset, shell=True) 
		subprocess.call('echo "OPTIONS yrev little_endian template" >> merg.ctl', shell=True)
		subprocess.call('echo "UNDEF  330" >> merg.ctl', shell=True)
		subprocess.call('echo "TITLE  globally merged IR data" >> merg.ctl', shell=True)
		subprocess.call('echo "XDEF 9896 LINEAR   0.0182 0.036378335" >> merg.ctl', shell=True)
		subprocess.call('echo "YDEF 3298 LINEAR   -59.982 0.036383683" >> merg.ctl', shell=True)
		subprocess.call('echo "ZDEF   01 LEVELS 1" >> merg.ctl', shell=True)
		subprocess.call(replaceExpTdef, shell=True)
		subprocess.call('echo "VARS 1" >> merg.ctl', shell=True)
		subprocess.call('echo "ch4  1  -1,40,1,-1 IR BT  (add  "75" to this value)" >> merg.ctl', shell=True)
		subprocess.call('echo "ENDVARS" >> merg.ctl', shell=True)

		#generate the lats4D command for GrADS
		lats4D = 'lats4d -v -q -lat '+LATMIN + ' ' +LATMAX +' -lon ' +LONMIN +' ' +LONMAX +' -time '+hr+'Z'+day+mth+yy + ' -func @+75 ' + '-i merg.ctl' + ' -o ' + fname
		
		#lats4D = 'lats4d -v -q -lat -40 -15 -lon 10 40 -time '+hr+'Z'+day+mth+yy + ' -func @+75 ' + '-i merg.ctl' + ' -o ' + fname
		#lats4D = 'lats4d -v -q -lat -5 40 -lon -90 60 -func @+75 ' + '-i merg.ctl' + ' -o ' + fname

		gradscmd = 'grads -blc ' + '\'' +lats4D + '\''
		#run grads and lats4d command
		subprocess.call(gradscmd, shell=True)
		imgFilename = hr+'Z'+day+mth+yy+'.gif'
		tempMaskedImages(imgFilename)

	#when all the files have benn converted, mv the netcdf files
	subprocess.call('mkdir mergNETCDF', shell=True)
	subprocess.call('mv *.nc mergNETCDF', shell=True)
	#mv all images
	subprocess.call('mkdir mergImgs', shell=True)
	subprocess.call('mv *.gif mergImgs', shell=True)
	return
#******************************************************************
def postProcessingNetCDF(dataset, dirName = None):
	'''
	
	TODO: UPDATE TO PICK UP LIMITS FROM FILE FOR THE GRADS SCRIPTS

	Purpose::
	    Utility script displaying the data in generated NETCDF4 files 
	    in GrADS
	    NOTE: VERY RAW AND DIRTY 

	Input::
	    dataset: integer representing post-processed MERG (1) or TRMM data (2) or original MERG(3)
	    string: Directory to the location of the raw (MERG) files, preferably zipped
		
	Output::
	   images in location as specfied in the code

	Assumptions::
	   1 GrADS (http://www.iges.org/grads/gadoc/) and lats4D (http://opengrads.org/doc/scripts/lats4d/)
	     have been installed on the system and the user can access 
	   2 User can write files in location where script is being called	
	'''	
	
	coreDir = os.path.dirname(os.path.abspath(__file__))
	ImgFilename = ''
	frameList=[]
	fileList =[]
	lines =[]
	var =''
	firstTime = True
	printLine = 0
	lineNum = 1
	colorbarInterval=2
	#Just incase the X11 server is giving problems
	subprocess.call('export DISPLAY=:0.0', shell=True)

	prevFrameNum = 0

	if dataset == 1:
		var = 'ch4'
		ctlTitle = 'TITLE MCC search Output Grid: Time  lat lon'
		ctlLine = 'brightnesstemp=\>ch4     1  t,y,x    brightnesstemperature'
		origsFile = coreDir+"/../GrADSscripts/cs1.gs"
		gsFile = coreDir+"/../GrADSscripts/cs2.gs"
		sologsFile = coreDir+"/../GrADSscripts/mergeCE.gs"
		lineNum = 50
	
	elif dataset ==2:
		var = 'precipAcc'
		ctlTitle ='TITLE  TRMM MCS accumulated precipitation search Output Grid: Time  lat lon '
		ctlLine = 'precipitation_Accumulation=\>precipAcc     1  t,y,x    precipAccu'
		origsFile = coreDir+"/../GrADSscripts/cs3.gs"
		gsFile = coreDir+"/../GrADSscripts/cs4.gs"
		sologsFile = coreDir+"/../GrADSscripts/TRMMCE.gs"
		lineNum = 10

	elif dataset ==3:
		var = 'ch4'
		ctlTitle = 'TITLE MERG DATA'
		ctlLine = 'ch4=\>ch4     1  t,y,x    brightnesstemperature'
		domainLatCmd = '\''+'set lat '+ LATMIN+' '+LATMAX+'\''+'\n'
		domainLonCmd = '\''+'set lon '+ LONMIN+' '+LONMAX+'\''+'\n'
		origsFile = coreDir+"/../GrADSscripts/cs1.gs"
		sologsFile = coreDir+"/../GrADSscripts/infrared.gs"
		lineNum = 54			

	#sort files
	os.chdir((dirName+'/'))
	try:
		os.makedirs('ctlFiles')
	except:
		print "ctl file folder created already"
		
	files = filter(os.path.isfile, glob.glob("*.nc"))
	files.sort(key=lambda x: os.path.getmtime(x))
	for eachfile in files:
		fullFname = os.path.splitext(eachfile)[0]
		fnameNoExtension = fullFname.split('.nc')[0]
		
		if dataset == 2 and fnameNoExtension[:4] != "TRMM":
			continue

		if dataset == 1 or dataset == 2:
			frameNum = int((fnameNoExtension.split('CE')[0]).split('00F')[1])
		
		#create the ctlFile
		ctlFile1 = dirName+'/ctlFiles/'+fnameNoExtension + '.ctl'
		#the ctl file
		subprocessCall = 'rm ' +ctlFile1
		subprocess.call(subprocessCall, shell=True)
		subprocessCall = 'touch '+ctlFile1
		subprocess.call(subprocessCall, shell=True)
		lineToWrite = 'echo DSET ' + dirName+'/'+fnameNoExtension+'.nc' +' >>' + ctlFile1 
		subprocess.call(lineToWrite, shell=True)  
		lineToWrite = 'echo DTYPE netcdf >> '+ctlFile1
		subprocess.call(lineToWrite, shell=True)
		lineToWrite = 'echo UNDEF 0 >> '+ctlFile1
		subprocess.call(lineToWrite, shell=True)
		lineToWrite = 'echo '+ctlTitle+' >> '+ctlFile1
		subprocess.call(lineToWrite, shell=True)
		fname = dirName+'/'+fnameNoExtension+'.nc'
		if os.path.isfile(fname):	
			#open NetCDF file add info to the accu 
			print "opening file ", fname
			fileData = Dataset(fname,'r',format='NETCDF4')
			lats = fileData.variables['latitude'][:]
			lons = fileData.variables['longitude'][:]
			LONDATA, LATDATA = np.meshgrid(lons,lats)
			nygrd = len(LATDATA[:,0]) 
			nxgrd = len(LONDATA[0,:])
			fileData.close()
		lineToWrite = 'echo XDEF '+ str(nxgrd) + ' LINEAR ' + str(min(lons)) +' '+ str((max(lons)-min(lons))/nxgrd) +' >> ' +ctlFile1
		subprocess.call(lineToWrite, shell=True)
		lineToWrite = 'echo YDEF '+ str(nygrd)+' LINEAR  ' + str(min(lats)) + ' ' + str((max(lats)-min(lats))/nygrd) +' >> '+ctlFile1
		subprocess.call(lineToWrite, shell=True)
		lineToWrite = 'echo ZDEF   01 LEVELS 1 >> '+ctlFile1
		subprocess.call(lineToWrite, shell=True)
		lineToWrite = 'echo TDEF 99999 linear 31aug2009 1hr >> '+ctlFile1
		subprocess.call(lineToWrite, shell=True)
		lineToWrite = 'echo VARS 1 >> '+ctlFile1
		subprocess.call(lineToWrite, shell=True)
		lineToWrite ='echo '+ctlLine+' >> '+ctlFile1
		subprocess.call(lineToWrite, shell=True)
		lineToWrite = 'echo ENDVARS >>  '+ctlFile1
		subprocess.call(lineToWrite, shell=True)
		lineToWrite = 'echo  >>  '+ctlFile1
		subprocess.call(lineToWrite, shell=True)

		#create plot of just that data
		subprocessCall = 'cp '+ origsFile+' '+sologsFile
		subprocess.call(subprocessCall, shell=True)

		colorbarFile = coreDir+"/../GrADSscripts/cbarnskip.gs"

		ImgFilename = fnameNoExtension + '.gif'
					
		displayCmd = '\''+'d '+ var+'\''+'\n'
		newFileCmd = '\''+'open '+ ctlFile1+'\''+'\n'
		colorbarCmd = '\''+'run ' + colorbarFile + ' '+str(colorbarInterval)+'\''+'\n'
		printimCmd = '\''+'printim '+MAINDIRECTORY+'/images/'+ImgFilename+' x800 y600 white\''+'\n'
		quitCmd = '\''+'quit'+'\''+'\n'
			
		GrADSscript = open(sologsFile,'r+')
		lines1 = GrADSscript.readlines()
		GrADSscript.seek(0)
		lines1.insert((1),newFileCmd)
		lines1.insert((lineNum+1),displayCmd)
		lines1.insert((lineNum+2), colorbarCmd)
		lines1.insert((lineNum+3), printimCmd)
		lines1.insert((lineNum + 4), quitCmd)

		if dataset == 3:
			lines1.insert((8),domainLatCmd)
			lines1.insert((9),domainLonCmd)
		
		GrADSscript.writelines(lines1)
		GrADSscript.close()
		#run the script
		runGrads = 'run '+ sologsFile
		gradscmd = 'grads -blc ' + '\'' +runGrads + '\''+'\n'
		subprocess.call(gradscmd, shell=True)

		if dataset == 1 or dataset == 2:

			if prevFrameNum != frameNum and firstTime == False:
				#counter for number of files (and for appending info to lines)
				count = 0
				subprocessCall = 'cp '+ origsFile+ ' '+gsFile
				subprocess.call(subprocessCall, shell=True)
				for fileName in frameList:
					if count == 0:
						frame1 = int((fileName.split('.nc')[0].split('CE')[0]).split('00F')[1])

					fnameNoExtension = fileName.split('.nc')[0]
					frameNum = int((fnameNoExtension.split('CE')[0]).split('00F')[1])
					
					if frameNum == frame1: 
						CE_num = fnameNoExtension.split('CE')[1]
						ImgFilename = fnameNoExtension.split('CE')[0] + '.gif'
						ctlFile1 = dirName+'/ctlFiles/'+fnameNoExtension + '.ctl'

						#build cs.gs script will all the CE ctl files and the appropriate display command
						newVar = var+'.'+CE_num
						newDisplayCmd = '\''+'d '+ newVar+'\''+'\n'
						newFileCmd = '\''+'open '+ ctlFile1+'\''+'\n'
						GrADSscript = open(gsFile,'r+')
						lines1 = GrADSscript.readlines()
						GrADSscript.seek(0)
						lines1.insert((1+count),newFileCmd)
						lines1.insert((lineNum+count+1),newDisplayCmd)
						GrADSscript.writelines(lines1)
						GrADSscript.close()
					count +=1

				colorbarCmd = '\''+'run cbarn'+'\''+'\n'
				printimCmd = '\''+'printim '+MAINDIRECTORY+'/images/'+ImgFilename+' x800 y600 white\''+'\n'
				quitCmd = '\''+'quit'+'\''+'\n'
				GrADSscript = open(gsFile,'r+')
				lines1 = GrADSscript.readlines()
				GrADSscript.seek(0)
				lines1.insert((lineNum+(count*2)+1), colorbarCmd)
				lines1.insert((lineNum + (count*2)+2), printimCmd)
				lines1.insert((lineNum + (count*2)+3), quitCmd)
				GrADSscript.writelines(lines1)
				GrADSscript.close()
				
				#run the script
				runGrads = 'run '+ gsFile
				gradscmd = 'grads -blc ' + '\'' +runGrads + '\''+'\n'
				subprocess.call(gradscmd, shell=True)
				
				#remove the file data stuff
				subprocessCall = 'cd '+dirName
				
				#reset the list for the next frame
				fileList = frameList
				frameList = []
				for thisFile in fileList:
					if int(((thisFile.split('.nc')[0]).split('CE')[0]).split('00F')[1]) == frameNum:
						frameList.append(thisFile)
				frameList.append(eachfile)
				prevFrameNum = frameNum
				
			else:
				frameList.append(eachfile)
				prevFrameNum = frameNum
				firstTime = False
				
	return	
#******************************************************************	
def drawGraph (thisGraph, graphTitle, edgeWeight=None):
	'''
	Purpose:: 
		Utility function to draw graph in the hierachial format

	Input:: 
		thisGraph: a Networkx directed graph 
		graphTitle: a string representing the graph title
		edgeWeight: (optional) a list of integers representing the edge weights in the graph
	
	Output:: None

	'''
	
	imgFilename = MAINDIRECTORY+'/images/'+ graphTitle+".gif"
	fig=plt.figure(facecolor='white', figsize=(20,16), dpi=50) 
	
	edgeMax = [(u,v) for (u,v,d) in thisGraph.edges(data=True) if d['weight'] == edgeWeight[0]]
	edgeMin = [(u,v) for (u,v,d) in thisGraph.edges(data=True) if d['weight'] == edgeWeight[1]]
	edegeOverlap = [(u,v) for (u,v,d) in thisGraph.edges(data=True) if d['weight'] == edgeWeight[2]]

	nx.write_dot(thisGraph, 'test.dot')
	plt.title(graphTitle)
	pos = nx.graphviz_layout(thisGraph, prog='dot',args='-Goverlap=false -Gsize="8.00,10.25"')
	#draw graph in parts
	#nodes
	nx.draw_networkx_nodes(thisGraph, pos, with_labels=True, labeldistance=25, labelfontsize=40, arrows=False, args='-Gsize="8.00,10.25"', node_size=1, nodesep='0.75')#,size="7.75,10.25")
	#edges
	nx.draw_networkx_edges(thisGraph, pos, edgelist=edgeMax, alpha=0.5, arrows=False) 
	nx.draw_networkx_edges(thisGraph, pos, edgelist=edgeMin,  edge_color='b', style='dashed', arrows=False)
	nx.draw_networkx_edges(thisGraph, pos, edgelist=edegeOverlap, edge_color='y', style='dashed', arrows=False)
	#labels
	nx.draw_networkx_labels(thisGraph,pos, arrows=False, font_size=14,font_family='sans-serif')
	
	cut = 1.05 #1.00
	xmax = cut * max(xx for xx, yy in pos.values())
	ymax = cut * max(yy for xx, yy in pos.values())
	plt.xlim(0, xmax)
	plt.ylim(0, ymax)

	plt.axis('off')
	plt.savefig(imgFilename, facecolor=fig.get_facecolor(), transparent=True)
	#do some clean up...and ensuring that we are in the right dir
	os.chdir((MAINDIRECTORY+'/'))
	subprocess.call('rm test.dot', shell=True)
#******************************************************************
def tempMaskedImages(imgFilename):
	'''
	Purpose:: 
		To generate temperature-masked images for a first pass verification

	Input::
	    imgFilename: filename for the gif file
		
	Output::
	    None - Gif images for each file of T_bb less than 250K are generated in folder called mergImgs

	Assumptions::
	   Same as for preprocessingMERG
	   1 GrADS (http://www.iges.org/grads/gadoc/) and lats4D (http://opengrads.org/doc/scripts/lats4d/)
	     have been installed on the system and the user can access 
	   2 User can write files in location where script is being called
	   3 the files havent been unzipped	
	'''
	
	subprocess.call('rm tempMaskedImages.gs', shell=True)
	subprocess.call('touch tempMaskedImages.gs', shell=True)
	subprocess.call('echo "''\'open merg.ctl''\'" >> tempMaskedImages.gs', shell=True)
	subprocess.call('echo "''\'set mpdset hires''\'" >> tempMaskedImages.gs', shell=True)
	subprocess.call('echo "''\'set lat -5 30''\'" >> tempMaskedImages.gs', shell=True)
	subprocess.call('echo "''\'set lon -40 30''\'" >> tempMaskedImages.gs', shell=True)
	subprocess.call('echo "''\'set cint 10''\'" >> tempMaskedImages.gs', shell=True)
	subprocess.call('echo "''\'set clevs 190 200 210 220 230 240 250''\'" >> tempMaskedImages.gs', shell=True)
	subprocess.call('echo "''\'set gxout shaded''\'" >> tempMaskedImages.gs', shell=True)
	subprocess.call('echo "''\'d ch4+75''\'" >> tempMaskedImages.gs', shell=True)
	subprocess.call('echo "''\'run cbarn''\'" >> tempMaskedImages.gs', shell=True)
	subprocess.call('echo "''\'draw title Masked Temp @ '+imgFilename +'\'" >> tempMaskedImages.gs', shell=True)
	subprocess.call('echo "''\'printim '+imgFilename +' x1000 y800''\'" >> tempMaskedImages.gs', shell=True)
	subprocess.call('echo "''\'quit''\'" >> tempMaskedImages.gs', shell=True)
	gradscmd = 'grads -blc ' + '\'run tempMaskedImages.gs''\'' 
	subprocess.call(gradscmd, shell=True)
	return
#******************************************************************
def gridPointData(dirName,startTime, endTime,hour, filelist=None):
	'''
	TODO: break out into a class for the file manipulation
	Purpose:: To grid (and interpolate) point data on the main (MERG) grid
			  (written to open WWLLN lightning data (http://wwlln.net/) currently, see TODO)
			  To allow for any data between the times to be gridded, even if some days are missing

	Input:: dirname: a string representing the directory to where the point data files areaAvg
			filelist: a list of strings representing the file names
			fileFormat: a dictionary representing the format of the data columns

	Output:: A number of netCDF files of the gridded point data

	Assumptions: the original point data are available in date stamped files i.e. each file = 1 day and
			are the same file format

	'''

	dataArray =[]
	count =1

	if filelist == None:
		filelistInstructions = dirName + '/*'
		filelist = glob.glob(filelistInstructions)


	filelist.sort()
	nfiles = len(filelist)

	# Crash nicely if there are no files
	if nfiles == 0:
		print 'Error: no files in this directory! Exiting elegantly'
		sys.exit()
	else:
		#create directory where the new files will be saved
		os.chdir((dirName))
		#create the subdirectories
		try:	
			os.makedirs('netCDFs')
		except:
			print "Directory exists already!!!"
	
	for file in filelist:
		print "lightning file ", file
		convertfunc = lambda x: datetime.strptime(x, "%Y/%m/%d")
		convertfunc2 = lambda x: datetime.strptime(x[0:8], "%H:%M:%S")
		fullDataArray = np.genfromtxt(file, delimiter=",", converters={0:convertfunc,1:convertfunc2})
		
		print "*************"
		
		#while the hr is correct, store the info in a temp array
		for x in fullDataArray:
			# print "hour ", hour
			# print "de hr ", x[1]
			# print "thishour ", str(x[1])[-9:-6]
			if int(str(x[1])[-8:-6]) == hour:
				dataArray.append((x))
				count += 1
			else:
				break

		#plot the points and the number of stations noticing the flash 
		#get data
		dataValues = [x[5] for x in dataArray]
		dataLats = [x[2] for x in dataArray]
		dataLons = [x[3] for x in dataArray]
		#interpolate data unto grid
		newData=griddata(dataLats, dataLons, dataValues, LON[:,0],LAT[0,:],interp='linear')
		fig,ax = plt.subplots(1, facecolor='white', figsize=(10,8))

		#map stuff 
		map = Basemap(projection='merc', llcrnrlat=-5,urcrnrlat=30,llcrnrlon=-20,urcrnrlon=10,lat_ts=20,resolution='c')
		map.drawcoastlines()
		x,y=map(dataLons, dataLats)
		map.scatter(x,y,marker='o',c=dataValues, cmap=cm.hsv)

		plt.colorbar()
		plt.title('scattering lightning data ')
		plt.show()

		
		sys.exit()
		# try:
		# 	#open file into netCDF array
		# 	convertfunc = lambda x: datetime.strptime(x, "%Y/%m/%d")
		# 	convertfunc2 = lambda x: datetime.strptime(x[0:8], "%H:%M:%S")
		# 	dataArray = np.genfromtxt(file, delimiter=",", converters={0:convertfunc,1:convertfunc2})
			
		# 	#interpolate data unto grid
		# 	dataValues = [x[5] for x in dataArray]
		# 	dataLats = [x[2] for x in dataArray]
		# 	dataLons = [x[3] for x in dataArray]
		# 	dataCoords = np.vstack((np.array(dataLats),np.array(dataLons)))
		# 	newData=griddata(dataCoords, dataValues(LAT,LON), method='linear')
		# 	plt.imshow(newData)

		# 	sys.exit()

		# 	#save as netcdf file

		# except:
		# 	print "File missing ", file
			#create netcdf with missing value identifier -999
	
	return
#******************************************************************
def getMCCListFromFile():
	'''
	Purpose:: 
		To extract each MCC node from the list in the textfile created 

	Input::
		None 

	Output::
		MCCListFromFile: a list of lists of strings representing each MCC in the file

	'''
	MCCListFromFile =[]
	if os.path.exists(MAINDIRECTORY+"/textFiles"):
		#check for the file
		currFilename = MAINDIRECTORY+"/textFiles/MCSPostPrecessing.txt" 
		if not os.path.isfile(currFilename):
			print "file is missing! Filename: ", currFilename
		else:
			file_obj = open(currFilename, 'r')
			for eachLine in file_obj:
				eachLine = re.sub('[\[\]]','',eachLine)
				lineList = re.sub("[^\w]"," ",eachLine).split()
				MCCListFromFile.append(lineList)
	else:
		"Error path is inaccurate"

	return MCCListFromFile		
#******************************************************************
# 
#             METRICS FUNCTIONS FOR MERG.PY
# TODO: rewrite these metrics so that they use the data from the 
#	file instead of the graph as this reduce mem resources needed
#	
#
#******************************************************************
def numberOfFeatures(finalMCCList):
	'''
	Purpose:: 
		To count the number of MCCs found for the period

	Input:: 
		finalMCCList: a list of list of strings representing a list of list of nodes representing a MCC
	
	Output::
		an integer representing the number of MCCs found

	'''
	return len(finalMCCList)
#******************************************************************
def temporalAndAreaInfoMetric(finalMCCList):
	'''
	Purpose:: 
		To provide information regarding the temporal properties of the MCCs found

	Input:: 
		finalMCCList: a list of dictionaries representing a list of nodes representing a MCC
	
	Output:: 
		allMCCtimes: a list of dictionaries {MCCtimes, starttime, endtime, duration, area} representing a list of dictionaries
			of MCC temporal details for each MCC in the period considered

	Assumptions:: 
		the final time hour --> the event lasted throughout that hr, therefore +1 to endtime
	'''
	#TODO: in real data edit this to use datetime
	#starttime =0
	#endtime =0
	#duration = 0
	MCCtimes =[]
	allMCCtimes=[]
	MCSArea =[]
	
	if finalMCCList:
		for eachMCC in finalMCCList:
			#get the info from the node
			for eachNode in eachMCC:
				MCCtimes.append(thisDict(eachNode)['cloudElementTime'])
				MCSArea.append(thisDict(eachNode)['cloudElementArea'])
			
			#sort and remove duplicates 
			MCCtimes=list(set(MCCtimes))
			MCCtimes.sort()
			tdelta = MCCtimes[1] - MCCtimes[0]
			starttime = MCCtimes[0]
			endtime = MCCtimes[-1]
			duration = (endtime - starttime) + tdelta
			print "starttime ", starttime, "endtime ", endtime, "tdelta ", tdelta, "duration ", duration, "MCSAreas ", MCSArea
			allMCCtimes.append({'MCCtimes':MCCtimes, 'starttime':starttime, 'endtime':endtime, 'duration':duration, 'MCSArea': MCSArea})
			MCCtimes=[]
			MCSArea=[]
	else:
		allMCCtimes =[]
		tdelta = 0 

	return allMCCtimes, tdelta
#******************************************************************
def longestDuration(allMCCtimes):
	'''
	Purpose:: 
		To determine the longest MCC for the period

	Input:: 
		allMCCtimes: a list of dictionaries {MCCtimes, starttime, endtime, duration, area} representing a list of dictionaries
			of MCC temporal details for each MCC in the period considered

	Output::
		an integer - lenMCC: representing the duration of the longest MCC found
	       a list of strings - longestMCC: representing the nodes of longest MCC

	Assumptions:: 

	'''

	# MCCList = []
	# lenMCC = 0
	# longestMCC =[]

	# #remove duplicates
	# MCCList = list(set(finalMCCList))

	# longestMCC = max(MCCList, key = lambda tup:len(tup))
	# lenMCC = len(longestMCC)

	# return lenMCC, longestMCC

	return max([MCC['duration'] for MCC in allMCCtimes])
#******************************************************************
def shortestDuration(allMCCtimes):
	'''
	Purpose:: To determine the shortest MCC for the period

	Input:: list of dictionaries - allMCCtimes {MCCtimes, starttime, endtime, duration): a list of dictionaries
			  of MCC temporal details for each MCC in the period considered

	Output::an integer - lenMCC: representing the duration of the shortest MCC found
	        a list of strings - longestMCC: representing the nodes of shortest MCC

	Assumptions:: 

	'''
	# lenMCC = 0
	# shortestMCC =[]
	# MCCList =[]
	
	# #remove duplicates
	# MCCList = list(set(finalMCCList))

	# shortestMCC = min(MCCList, key = lambda tup:len(tup))
	# lenMCC = len(shortestMCC)

	# return lenMCC, shortestMCC
	return min([MCC['duration'] for MCC in allMCCtimes])
#******************************************************************
def averageDuration(allMCCtimes):
	'''
	Purpose:: To determine the average MCC length for the period

	Input:: list of dictionaries - allMCCtimes {MCCtimes, starttime, endtime, duration): a list of dictionaries
			  of MCC temporal details for each MCC in the period considered

	Output::a floating-point representing the average duration of a MCC in the period
	        
	Assumptions:: 

	'''

	return sum([MCC['duration'] for MCC in allMCCtimes], timedelta(seconds=0))/len(allMCCtimes)
#******************************************************************
def averageTime (allTimes):
	'''
	Purpose:: 
		To determine the average time in a list of datetimes 
		e.g. of use is finding avg starttime, 
	Input:: 
		allTimes: a list of datetimes representing all of a given event e.g. start time

	Output:: 
		a floating-point number representing the average of the times given

	'''
	avgTime = 0

	for aTime in allTimes:
		avgTime += aTime.second + 60*aTime.minute + 3600*aTime.hour

	if len(allTimes) > 1:
		avgTime /= len(allTimes)
	
	rez = str(avgTime/3600) + ' ' + str((avgTime%3600)/60) + ' ' + str(avgTime%60)
	return datetime.strptime(rez, "%H %M %S")
#******************************************************************
def averageFeatureSize(finalMCCList): 
	'''
	Purpose:: To determine the average MCC size for the period

	Input:: a list of list of strings - finalMCCList: a list of list of nodes representing a MCC
	
	Output::a floating-point representing the average area of a MCC in the period
	        
	Assumptions:: 

	'''
	thisMCC = 0.0
	thisMCCAvg = 0.0

	#for each node in the list, get the are information from the dictionary
	#in the graph and calculate the area
	for eachPath in finalMCCList:
		for eachNode in eachPath:
			thisMCC += thisDict(eachNode)['cloudElementArea']

		thisMCCAvg += (thisMCC/len(eachPath))
		thisMCC = 0.0

	#calcuate final average
	return thisMCCAvg/(len(finalMCCList))
#******************************************************************
def commonFeatureSize(finalMCCList): 
	'''
	Purpose:: 
		To determine the common (mode) MCC size for the period

	Input:: 
		finalMCCList: a list of list of strings representing the list of nodes representing a MCC
	
	Output::
		a floating-point representing the average area of a MCC in the period
	        
	Assumptions:: 

	'''
	thisMCC = 0.0
	thisMCCAvg = []

	#for each node in the list, get the area information from the dictionary
	#in the graph and calculate the area
	for eachPath in finalMCCList:
		for eachNode in eachPath:
			thisMCC += eachNode['cloudElementArea']

		thisMCCAvg.append(thisMCC/len(eachPath))
		thisMCC = 0.0

	#calcuate 
	hist, bin_edges = np.histogram(thisMCCAvg)
	return hist,bin_edges
#******************************************************************
def precipTotals(finalMCCList):
	'''
	Purpose:: 
		Precipitation totals associated with a cloud element

	Input:: 
		finalMCCList: a list of dictionaries representing a list of nodes representing a MCC

	Output:: 
		precipTotal: a floating-point number representing the total amount of precipitation associated 
			with the feature
	'''
	precipTotal = 0.0
	CEprecip =0.0
	MCSPrecip=[]
	allMCSPrecip =[]
	count = 0

	if finalMCCList:
		#print "len finalMCCList is: ", len(finalMCCList)
		for eachMCC in finalMCCList:
			#get the info from the node
			for node in eachMCC:
				eachNode=thisDict(node)
				count += 1
				if count == 1:
					prevHr = int(str(eachNode['cloudElementTime']).replace(" ", "")[-8:-6])
				
				currHr =int(str(eachNode['cloudElementTime']).replace(" ", "")[-8:-6])
				if prevHr == currHr:
					CEprecip += eachNode['cloudElementPrecipTotal'] 
				else:
					MCSPrecip.append((prevHr,CEprecip))
					CEprecip = eachNode['cloudElementPrecipTotal'] 
				#last value in for loop
				if count == len(eachMCC):
					MCSPrecip.append((currHr, CEprecip))

				precipTotal += eachNode['cloudElementPrecipTotal'] 
				prevHr = currHr

			MCSPrecip.append(('0',precipTotal))
			
			allMCSPrecip.append(MCSPrecip)
			precipTotal =0.0
			CEprecip = 0.0
			MCSPrecip = []
			count = 0

		print "allMCSPrecip ", allMCSPrecip

	return allMCSPrecip
#******************************************************************
def precipMaxMin(finalMCCList):
	'''
	TODO: this doesnt work the np.min/max function seems to be not working with the nonzero option..possibly a problem upstream with cloudElementLatLonTRMM
	Purpose:: 
		Precipitation maximum and min rates associated with each CE in MCS
	Input:: 
		finalMCCList: a list of dictionaries representing a list of nodes representing a MCC

	Output::
		MCSPrecip: a list indicating max and min rate for each CE identified

	'''
	maxCEprecip = 0.0
	minCEprecip =0.0
	MCSPrecip=[]
	allMCSPrecip =[]


	if finalMCCList:
		if type(finalMCCList[0]) is str: # len(finalMCCList) == 1:
			for node in finalMCCList:
				eachNode = thisDict(node)
				CETRMM = eachNode['cloudElementLatLonTRMM']

				print "all ", np.min(CETRMM[np.nonzero(CETRMM)])
				print "minCEprecip ", np.min(eachNode['cloudElementLatLonTRMM']) #[np.nonzero(eachNode['cloudElementLatLonTRMM'])])

				print "maxCEprecip ", np.max(eachNode['cloudElementLatLonTRMM'][np.nonzero(eachNode['cloudElementLatLonTRMM'])])
				sys.exit()
				maxCEprecip = np.max(eachNode['cloudElementLatLonTRMM'][np.nonzero(eachNode['cloudElementLatLonTRMM'])])
				minCEprecip = np.min(eachNode['cloudElementLatLonTRMM'][np.nonzero(eachNode['cloudElementLatLonTRMM'])])
				MCSPrecip.append((eachNode['uniqueID'],minCEprecip, maxCEprecip))
			
		else:
			for eachMCC in finalMCCList:
				#get the info from the node
				for node in eachMCC: 
					eachNode=thisDict(node)
					#find min and max precip
					maxCEprecip =  np.max(eachNode['cloudElementLatLonTRMM'][np.nonzero(eachNode['cloudElementLatLonTRMM'])])
					minCEprecip =  np.min(eachNode['cloudElementLatLonTRMM'][np.nonzero(eachNode['cloudElementLatLonTRMM'])])
					MCSPrecip.append((eachNode['uniqueID'],minCEprecip, maxCEprecip))
				allMCSPrecip.append(MCSPrecip)
				MCSPrecip =[]
	 
	return MCSPrecip
#******************************************************************
def compareToMthlyTotal(MCCListOfLists, monthlyTRMM):
	'''
	Purpose:: To determine the percentage contribution of each MCC 
		to the monthly total

	Input:: MCCListOfLists: a list of lists of strings representing 
		each node in each MCC (each list)
			monthlyTRMM: a string representing the file (with path) of the TRMM file

	Output:: a list of floating-points the percentage contribution 
		a floating-point of the average contribution
		a floating-point of the total contribution

	'''

	int nextMth = 0
	int currMth = 0

	for MCCList in MCCListOfLists:
		firstNode = MCCList[0]
		firstNodeDateTime = thisDict(MCCList[0])
		if firstNodeDateTime['cloudElementTime'][5:7] == nextMth:
			#close currMthFile #currMthFile.close
			#generate graphic for that month of data
			# and stats for that mth 
			#assign currMth dict to {}
			#firstTimeFlag == True

		for eachNode in MCCList:
			thisNodeTimeDate = thisDict[0]
			thisNodeYear = thisNodeTimeDate[0:4]
			thisNodeMth = thisNodeTimeDate[5:7]
			if firstTimeFlag == True:
				currMth = int(thisNodeMth)
				currYr = int(thisNodeYear)
				firstTimeFlag = False
				currMthDate = openMthlyTRMM(currMth)

			if int(thisNodeMth) == currMth and int(thisNodeYear) == currYr:
				#compareMCCToMthlyTotal()
				openNodeTRMMRR(eachNode)
			else:
				nextMth = int(thisNodeMth)
				nextMthDict = openMthlyTRMM(nextMth)
				#compareMCCToMthlyTotal()


		#leave the clipping until the end
		#get the relevant TRMM info 
		allMCCsPrecip = regriddedTRMM[latStartIndexOffset:(latEndIndexOffset+1), lonStartIndexOffset:(lonEndIndexOffset+1)]
		
		#get the relevant TRMM info from the monthly file
		mthlyPrecipRate = regriddedmthlyTRMM[latStartIndexOffset:(latEndIndexOffset+1), lonStartIndexOffset:(lonEndIndexOffset+1)]
		
		eachCellContribution = ma.zeros(mthlyPrecipRate.shape)
		eachCellContribution = allMCCsPrecip/mthlyPrecipRate
		eachContributionLess = ma.masked_array(eachCellContribution, mask=(eachCellContribution >= 1.0))
		eachContributionMore = ma.masked_array(eachCellContribution, mask=(eachCellContribution <= 1.0))
		
		# generate plot info and create the plots
		#viewMthlyTotals(eachCellContribution,latBandMin, latBandMax, lonBandMin, lonBandMax)
		title = 'Each MCC contribution to the monthly TRMM total'
		imgFilename = MAINDIRECTORY+'/images/MCCContribution.gif'
		clevs = np.arange(0,100,5)
		infoDict ={'dataset':eachContributionLess*100.0, 'imgFilename':imgFilename, 'title':title,'clevs':clevs, 'latBandMin': latBandMin, 'latBandMax': latBandMax, 'lonBandMin': lonBandMin, 'lonBandMax': lonBandMax}
		viewMthlyTotals(infoDict)
		#viewMthlyTotals(eachContributionLess*100.0,title, imgFilename, latBandMin, latBandMax, lonBandMin, lonBandMax)
		
		title = 'MCC contributions that exceed the monthly TRMM total'
		imgFilename = MAINDIRECTORY+'/images/MCCexceedTRMM.gif'	
		clevs = np.arange(100,float(np.max(eachContributionMore))*100 + 5,5)
		infoDict ={'dataset':eachContributionMore*100.0, 'imgFilename':imgFilename, 'title':title,'clevs':clevs, 'latBandMin': latBandMin, 'latBandMax': latBandMax, 'lonBandMin': lonBandMin, 'lonBandMax': lonBandMax}
		viewMthlyTotals(infoDict)

#******************************************************************
def compareToMthlyTotalOld(MCCListOfLists, monthlyTRMM):
	'''
	Purpose:: To determine the percentage contribution of each MCC 
		to the monthly total

	Input:: MCCListOfLists: a list of lists of strings representing 
		each node in each MCC (each list)
			monthlyTRMM: a string representing the file (with path) of the TRMM file

	Output:: a list of floating-points the percentage contribution 
		a floating-point of the average contribution
		a floating-point of the total contribution

	'''
	firstTime = False
	mccCount = 0
	MCCsContribution =[] #list to hold each MCCs contribution to the monthly RR as a ratio
	eachMCCtotal = [] 
	eachMCCTotalCmpToMth = []
	latBandMin = 5.0 #floating point representing the min lat for the region being considered
	latBandMax = 20.0 #floating point representing the max lat for the region being considered
	lonBandMin = -15.0 #floating point representing the min lon for the region being considered
	lonBandMax = 10.0 #floating point representing the max lon for the region being considered	

	# these strings are specific to the MERG data
	mergVarName = 'ch4'
	mergTimeVarName = 'time'
	mergLatVarName = 'latitude'
	mergLonVarName = 'longitude'

	#open a fulldisk merg file to get the full dimensions 
	#TODO: find a neater way of doing this
	tmp = Nio.open_file("/Users/kimwhitehall/Documents/HU/postDoc/paper/mergNETCDF/merg_2013080923_4km-pixel.nc", format='nc')
	
	#clip the lat/lon grid according to user input
	#http://www.pyngl.ucar.edu/NioExtendedSelection.shtml
	#TODO: figure out how to use netCDF4 to do the clipping tmp = netCDF4.Dataset(filelist[0])
	latsraw = tmp.variables[mergLatVarName][:].astype('f2')
	lonsraw = tmp.variables[mergLonVarName][:].astype('f2')
	lonsraw[lonsraw > 180] = lonsraw[lonsraw > 180] - 360.  # convert to -180,180 if necessary
	
	LON, LAT = np.meshgrid(lonsraw, latsraw)
	nygrd = len(LAT[:, 0]); nxgrd = len(LON[0, :])
	
	# #TODO: determine the monthly data file to be opened as opposed to hard coding it
	# #open the monthly data
	# TRMMmthData = Dataset(monthlyTRMM,'r',format='NETCDF4')
	# #convert precip rate mm/hr to monthly value i.e. *(24*31) as Jul in this case
	# mthlyPrecipRate = (TRMMmthData.variables['pcp'][:,:,:])*24*31
	# latsrawTRMMData = TRMMmthData.variables['latitude'][:]
	# lonsrawTRMMData = TRMMmthData.variables['longitude'][:]
	# lonsrawTRMMData[lonsrawTRMMData > 180] = lonsrawTRMMData[lonsrawTRMMData>180] - 360.
	# LONTRMM, LATTRMM = np.meshgrid(lonsrawTRMMData, latsrawTRMMData)

	# nygrdTRMM = len(LATTRMM[:,0]); nxgrdTRMM = len(LONTRMM[0,:])
	
	# mthlyPrecipRateMasked = ma.masked_array(mthlyPrecipRate, mask=(mthlyPrecipRate < 0.0))
	# mthlyPrecipRate =[]
	
	# #regrid the monthly dataset to the MERG grid as the TRMMNETCDFCEs are 4km regridded as well. 
	# #---------regrid the TRMM data to the MERG dataset ----------------------------------
	# #regrid using the do_regrid stuff from the Apache OCW 
	# regriddedmthlyTRMM = ma.zeros((1, nygrd, nxgrd))
	# #TODO: **ThE PROBLEM **** this regridding is an issue because the regrid occurs only over the lat lons given in the main prog and not
	# #necessarily the lat lons given for the mthlyprecip domain
	# #dirty fix: open a full original merg file to get reset the LAT LONS values
	# regriddedmthlyTRMM = process.do_regrid(mthlyPrecipRateMasked[0,:,:], LATTRMM,  LONTRMM, LAT, LON, order=1, mdi= -999999999)
	# regriddedTRMM = ma.zeros((regriddedmthlyTRMM.shape))
	# #----------------------------------------------------------------------------------
	# #get the lat/lon info for TRMM data (different resolution)
	# latStartT = find_nearest(latsrawTRMMData, latBandMin)
	# latEndT = find_nearest(latsrawTRMMData, latBandMax)
	# lonStartT = find_nearest(lonsrawTRMMData, lonBandMin)
	# lonEndT = find_nearest(lonsrawTRMMData, lonBandMax)

	# latStartIndex = np.where(latsrawTRMMData == latStartT)
	# latEndIndex = np.where(latsrawTRMMData == latEndT)
	# lonStartIndex = np.where(lonsrawTRMMData == lonStartT)
	# lonEndIndex = np.where(lonsrawTRMMData == lonEndT)


	# latStartT = find_nearest(LAT[:,0], latBandMin)
	# latEndT = find_nearest(LAT[:,0], latBandMax)
	# lonStartT = find_nearest(LON[0,:], lonBandMin)
	# lonEndT = find_nearest(LON[0,:], lonBandMax)
	# latStartIndex = np.where(LAT[:,0] == latStartT)
	# latEndIndex = np.where(LAT[:,0] == latEndT)
	# lonStartIndex = np.where(LON[0,:] == lonStartT)
	# lonEndIndex = np.where(LON[0,:] == lonEndT)
	# latStartIndexOffset = latStartIndex[0][0]
	# latEndIndexOffset = latEndIndex[0][0]
	# lonStartIndexOffset = lonStartIndex[0][0]
	# lonEndIndexOffset = lonEndIndex[0][0]

	# #get the relevant TRMM info from the monthly file
	# mthlyPrecipRate = regriddedmthlyTRMM[latStartIndexOffset:latEndIndexOffset, lonStartIndexOffset:lonEndIndexOffset]
					
	# TRMMmthData.close()	
		
	#we will be using TRMM CE data only
	dirName = MAINDIRECTORY+'/TRMMnetcdfCEs'
	if not os.path.exists(dirName):
		print "Error in the directory"
	else:
		os.chdir((dirName))
		
	for eachlist in MCCListOfLists:
		if eachlist:
			mccCount +=1
			firstTime = True

			for eachNode in eachlist:
				#determine the filename to check, we will be using TRMM only
				cmdLine = 'ls *'+ eachNode + '.nc' #'*.nc'
				fileNameCmd = subprocess.Popen(cmdLine, stdout=subprocess.PIPE, shell=True)
				#ensure whitespaces at beginning and end are stripped
				fileName = (dirName+'/'+fileNameCmd.communicate()[0]).strip()
				
				#open file and create accumulation file (compare against the monthly one time too?)
				if os.path.exists(fileName):	
					#TODO: check if this file belongs to the current mthly TRMM file or, will it belong to the following mth

					#open NetCDF file add info to the accu 
					TRMMCEData = Dataset(fileName,'r',format='NETCDF4')
					precipRate = TRMMCEData.variables['precipitation_Accumulation'][:]
					lats = TRMMCEData.variables['latitude'][:]
					lons = TRMMCEData.variables['longitude'][:]
					lat_min = lats[0]
					lat_max = lats[-1]
					lon_min = lons[0]
					lon_max = lons[-1]

					LONTRMM, LATTRMM = np.meshgrid(lons,lats)
					nygrdTRMM = len(LATTRMM[:,0]) 
					nxgrdTRMM = len(LONTRMM[0,:])
					
					precipRate = ma.masked_array(precipRate, mask=(precipRate < 0.0))
					TRMMCEData.close()
				else:
					print "nah dread it aint here"
					#TODO: exit elegantly 
					sys.exit()
				
				if firstTime == True:
					#then clip the monthly dataset
					#find the min & max lat and lon of the TRMMNETCDF dataset and extract that data from the mthly file
					latStartIndex = np.where(LAT[:,0]==LATTRMM[0][0])[0][0]
					latEndIndex = np.where(LAT[:,0]==LATTRMM[-1][0])[0][0]
					lonStartIndex = np.where(LON[0,:]==LONTRMM[0][0])[0][0]
					lonEndIndex = np.where(LON[0,:]==LONTRMM[0][-1])[0][0]
					accuPrecipRate = ma.zeros((precipRate.shape))
					firstTime = False
				else:
					accuPrecipRate += precipRate
	
				#create new netCDF file to write the accumulated RR associated with the MCC
				#can remove here for checking purposes
				accuMCCFile = MAINDIRECTORY+'/TRMMnetcdfCEs/accuMCC'+str(mccCount)+'.nc'	
				accuMCCData = Dataset(accuMCCFile, 'w', format='NETCDF4')
				accuMCCData.description =  'Accumulated precipitation data'
				accuMCCData.calendar = 'standard'
				accuMCCData.conventions = 'COARDS'
				# dimensions
				accuMCCData.createDimension('time', None)
				accuMCCData.createDimension('lat', nygrdTRMM)
				accuMCCData.createDimension('lon', nxgrdTRMM)
				# variables
				MCCprecip = ('time','lat', 'lon',)
				times = accuMCCData.createVariable('time', 'f8', ('time',))
				latitude = accuMCCData.createVariable('latitude', 'f8', ('lat',))
				longitude = accuMCCData.createVariable('longitude', 'f8', ('lon',))
				rainFallacc = accuMCCData.createVariable('precipitation_Accumulation', 'f8',MCCprecip)
				rainFallacc.units = 'mm'

				longitude[:] = LONTRMM[0,:]
				longitude.units = "degrees_east" 
				longitude.long_name = "Longitude" 

				latitude[:] =  LATTRMM[:,0]
				latitude.units = "degrees_north"
				latitude.long_name ="Latitude"

				rainFallacc[:] = accuPrecipRate[:]

				accuMCCData.close()
				#end writing the file
				
			regriddedTRMM[latStartIndex:(latEndIndex +1),lonStartIndex:(lonEndIndex+1)] += np.squeeze(accuPrecipRate, axis=0)
			
			#append total of that MCC to totalMCCsInMth
			eachMCCtotal.append(accuPrecipRate.sum())

			#append the % contribution of the MCC to the month total within the domain
			eachMCCTotalCmpToMth.append(accuPrecipRate.sum()/regriddedmthlyTRMM[latStartIndex:(latEndIndex +1),lonStartIndex:(lonEndIndex+1)].sum())
	
	#leave the clipping until the end
	#get the relevant TRMM info 
	allMCCsPrecip = regriddedTRMM[latStartIndexOffset:(latEndIndexOffset+1), lonStartIndexOffset:(lonEndIndexOffset+1)]
	
	#get the relevant TRMM info from the monthly file
	mthlyPrecipRate = regriddedmthlyTRMM[latStartIndexOffset:(latEndIndexOffset+1), lonStartIndexOffset:(lonEndIndexOffset+1)]
	
	eachCellContribution = ma.zeros(mthlyPrecipRate.shape)
	eachCellContribution = allMCCsPrecip/mthlyPrecipRate
	eachContributionLess = ma.masked_array(eachCellContribution, mask=(eachCellContribution >= 1.0))
	eachContributionMore = ma.masked_array(eachCellContribution, mask=(eachCellContribution <= 1.0))
	
	# generate plot info and create the plots

	#viewMthlyTotals(eachCellContribution,latBandMin, latBandMax, lonBandMin, lonBandMax)
	title = 'Each MCC contribution to the monthly TRMM total'
	imgFilename = MAINDIRECTORY+'/images/MCCContribution.gif'
	clevs = np.arange(0,100,5)
	infoDict ={'dataset':eachContributionLess*100.0, 'imgFilename':imgFilename, 'title':title,'clevs':clevs, 'latBandMin': latBandMin, 'latBandMax': latBandMax, 'lonBandMin': lonBandMin, 'lonBandMax': lonBandMax}
	viewMthlyTotals(infoDict)
	#viewMthlyTotals(eachContributionLess*100.0,title, imgFilename, latBandMin, latBandMax, lonBandMin, lonBandMax)
	
	title = 'MCC contributions that exceed the monthly TRMM total'
	imgFilename = MAINDIRECTORY+'/images/MCCexceedTRMM.gif'	
	clevs = np.arange(100,float(np.max(eachContributionMore))*100 + 5,5)
	infoDict ={'dataset':eachContributionMore*100.0, 'imgFilename':imgFilename, 'title':title,'clevs':clevs, 'latBandMin': latBandMin, 'latBandMax': latBandMax, 'lonBandMin': lonBandMin, 'lonBandMax': lonBandMax}
	viewMthlyTotals(infoDict)
	#viewMthlyTotals(eachContributionMore*100.0,title, imgFilename, latBandMin, latBandMax, lonBandMin, lonBandMax)
#******************************************************************
def compareToMthlyTotalCall(starttime, endtime):
	'''
	Purpose:: 
		To determine the monthly contribution between some time period

	Input:: 
		starttime: a string representing the time to start the accumulations format yyyy-mm-dd_hh:mm:ss
		endtime: a string representing the time to end the accumulations format yyyy-mm-dd_hh:mm:ss
	
	Output:: 
		None
	'''

	currmth = 0
	sTime = datetime.strptime(starttime.replace("_"," "),'%Y-%m-%d %H:%M:%S')
	eTime = datetime.strptime(endtime.replace("_"," "),'%Y-%m-%d %H:%M:%S')
	thisTime = sTime

	MCCListOfListsForTheMonth = getMCCListFromFile()

	while thisTime <= eTime:
		month = thisTime[5:7]
		year = thisTime[:4]
		if currmth = 0:
			#open the file
			thisMthData = openMthlyTRMM(year,month)
			compareToMthlyTotal(MCCListOfListsForTheMonth, thisMthData)
		elif int(month) != currmth:
			nextMthData = openMthlyTRMM(year,month)
			compareToMthlyTotal(MCCListOfListsForTheMonth, nextMthData)
		# elif month == currmth:
		# 	#do the compareToMthlyTotal in same TRMM file,

		# 	currmth = month
		# else:
		# 	#if month greater
#******************************************************************
def openMthlyTRMM(year,mth):
	'''
	'''
	monthlyTRMM = "~/mthlyData/3B43."+year+mth+"01.7A.nc"
	#TODO: determine the monthly data file to be opened as opposed to hard coding it
	#open the monthly data
	TRMMmthData = Dataset(monthlyTRMM,'r',format='NETCDF4')
	#convert precip rate mm/hr to monthly value i.e. *(24*31) as Jul in this case
	mthlyPrecipRate = (TRMMmthData.variables['pcp'][:,:,:])*24*31
	latsrawTRMMData = TRMMmthData.variables['latitude'][:]
	lonsrawTRMMData = TRMMmthData.variables['longitude'][:]
	lonsrawTRMMData[lonsrawTRMMData > 180] = lonsrawTRMMData[lonsrawTRMMData>180] - 360.
	LONTRMM, LATTRMM = np.meshgrid(lonsrawTRMMData, latsrawTRMMData)

	nygrdTRMM = len(LATTRMM[:,0]); nxgrdTRMM = len(LONTRMM[0,:])
	
	mthlyPrecipRateMasked = ma.masked_array(mthlyPrecipRate, mask=(mthlyPrecipRate < 0.0))
	mthlyPrecipRate =[]
	
	#regrid the monthly dataset to the MERG grid as the TRMMNETCDFCEs are 4km regridded as well. 
	#---------regrid the TRMM data to the MERG dataset ----------------------------------
	#regrid using the do_regrid stuff from the Apache OCW 
	regriddedmthlyTRMM = ma.zeros((1, nygrd, nxgrd))
	#TODO: **ThE PROBLEM **** this regridding is an issue because the regrid occurs only over the lat lons given in the main prog and not
	#necessarily the lat lons given for the mthlyprecip domain
	#dirty fix: open a full original merg file to get reset the LAT LONS values
	regriddedmthlyTRMM = process.do_regrid(mthlyPrecipRateMasked[0,:,:], LATTRMM,  LONTRMM, LAT, LON, order=1, mdi= -999999999)
	regriddedTRMM = ma.zeros((regriddedmthlyTRMM.shape))
	#----------------------------------------------------------------------------------
	#get the lat/lon info for TRMM data (different resolution)
	latStartT = find_nearest(latsrawTRMMData, latBandMin)
	latEndT = find_nearest(latsrawTRMMData, latBandMax)
	lonStartT = find_nearest(lonsrawTRMMData, lonBandMin)
	lonEndT = find_nearest(lonsrawTRMMData, lonBandMax)

	latStartIndex = np.where(latsrawTRMMData == latStartT)
	latEndIndex = np.where(latsrawTRMMData == latEndT)
	lonStartIndex = np.where(lonsrawTRMMData == lonStartT)
	lonEndIndex = np.where(lonsrawTRMMData == lonEndT)


	latStartT = find_nearest(LAT[:,0], latBandMin)
	latEndT = find_nearest(LAT[:,0], latBandMax)
	lonStartT = find_nearest(LON[0,:], lonBandMin)
	lonEndT = find_nearest(LON[0,:], lonBandMax)
	latStartIndex = np.where(LAT[:,0] == latStartT)
	latEndIndex = np.where(LAT[:,0] == latEndT)
	lonStartIndex = np.where(LON[0,:] == lonStartT)
	lonEndIndex = np.where(LON[0,:] == lonEndT)
	latStartIndexOffset = latStartIndex[0][0]
	latEndIndexOffset = latEndIndex[0][0]
	lonStartIndexOffset = lonStartIndex[0][0]
	lonEndIndexOffset = lonEndIndex[0][0]

	#get the relevant TRMM info from the monthly file
	mthlyPrecipRate = regriddedmthlyTRMM[latStartIndexOffset:latEndIndexOffset, lonStartIndexOffset:lonEndIndexOffset]
					
	TRMMmthData.close()	

	return mth
#******************************************************************
def openTRMMRR(eachNode):
	'''
	Purpose::

	Input::

	Output::

	'''
	#we will be using TRMM CE data only
	dirName = MAINDIRECTORY+'/TRMMnetcdfCEs'
	if not os.path.exists(dirName):
		print "Error in the directory"
	else:
		os.chdir((dirName))
		
	#determine the filename to check, we will be using TRMM only
	cmdLine = 'ls *'+ eachNode + '.nc' #'*.nc'
	fileNameCmd = subprocess.Popen(cmdLine, stdout=subprocess.PIPE, shell=True)
	#ensure whitespaces at beginning and end are stripped
	fileName = (dirName+'/'+fileNameCmd.communicate()[0]).strip()
	
	#open file and create accumulation file (compare against the monthly one time too?)
	if os.path.exists(fileName):	
		#open NetCDF file add info to the accu 
		TRMMCEData = Dataset(fileName,'r',format='NETCDF4')
		precipRate = TRMMCEData.variables['precipitation_Accumulation'][:]
		lats = TRMMCEData.variables['latitude'][:]
		lons = TRMMCEData.variables['longitude'][:]
		lat_min = lats[0]
		lat_max = lats[-1]
		lon_min = lons[0]
		lon_max = lons[-1]

		LONTRMM, LATTRMM = np.meshgrid(lons,lats)
		nygrdTRMM = len(LATTRMM[:,0]) 
		nxgrdTRMM = len(LONTRMM[0,:])
		
		precipRate = ma.masked_array(precipRate, mask=(precipRate < 0.0))
		TRMMCEData.close()
	else:
		print "nah dread it aint here"
		#TODO: exit elegantly 
		sys.exit()

	if firstTime == True:
		#then clip the monthly dataset
		#find the min & max lat and lon of the TRMMNETCDF dataset and extract that data from the mthly file
		latStartIndex = np.where(LAT[:,0]==LATTRMM[0][0])[0][0]
		latEndIndex = np.where(LAT[:,0]==LATTRMM[-1][0])[0][0]
		lonStartIndex = np.where(LON[0,:]==LONTRMM[0][0])[0][0]
		lonEndIndex = np.where(LON[0,:]==LONTRMM[0][-1])[0][0]
		accuPrecipRate = ma.zeros((precipRate.shape))
		firstTime = False

	accuPrecipRate += precipRate
	accuMCCData.close()

	return latStartIndex, latEndIndex, lonStartIndex, lonEndIndex
	
	
	# #create new netCDF file to write the accumulated RR associated with the MCC
	# #can remove here for checking purposes
	# accuMCCFile = MAINDIRECTORY+'/TRMMnetcdfCEs/accuMCC'+str(mccCount)+'.nc'	
	# accuMCCData = Dataset(accuMCCFile, 'w', format='NETCDF4')
	# accuMCCData.description =  'Accumulated precipitation data'
	# accuMCCData.calendar = 'standard'
	# accuMCCData.conventions = 'COARDS'
	# # dimensions
	# accuMCCData.createDimension('time', None)
	# accuMCCData.createDimension('lat', nygrdTRMM)
	# accuMCCData.createDimension('lon', nxgrdTRMM)
	# # variables
	# MCCprecip = ('time','lat', 'lon',)
	# times = accuMCCData.createVariable('time', 'f8', ('time',))
	# latitude = accuMCCData.createVariable('latitude', 'f8', ('lat',))
	# longitude = accuMCCData.createVariable('longitude', 'f8', ('lon',))
	# rainFallacc = accuMCCData.createVariable('precipitation_Accumulation', 'f8',MCCprecip)
	# rainFallacc.units = 'mm'

	# longitude[:] = LONTRMM[0,:]
	# longitude.units = "degrees_east" 
	# longitude.long_name = "Longitude" 

	# latitude[:] =  LATTRMM[:,0]
	# latitude.units = "degrees_north"
	# latitude.long_name ="Latitude"

	# rainFallacc[:] = accuPrecipRate[:]

	
	#end writing the file
	
# regriddedTRMM[latStartIndex:(latEndIndex +1),lonStartIndex:(lonEndIndex+1)] += np.squeeze(accuPrecipRate, axis=0)

# #append total of that MCC to totalMCCsInMth
# eachMCCtotal.append(accuPrecipRate.sum())

# #append the % contribution of the MCC to the month total within the domain
# eachMCCTotalCmpToMth.append(accuPrecipRate.sum()/regriddedmthlyTRMM[latStartIndex:(latEndIndex +1),lonStartIndex:(lonEndIndex+1)].sum())
#******************************************************************
# def compareToMthlyTotal(MCCListOfLists, monthlyTRMM):
# 	'''
# 	Purpose:: To determine the percentage contribution of each MCC 
# 		to the monthly total

# 	Input:: MCCListOfLists: a list of lists of strings representing 
# 		each node in each MCC (each list)
# 			monthlyTRMM: a string representing the file (with path) of the TRMM file

# 	Output:: a list of floating-points the percentage contribution 
# 		a floating-point of the average contribution
# 		a floating-point of the total contribution

# 	'''
# 	firstTime = False
# 	mccCount = 0
# 	MCCsContribution =[] #list to hold each MCCs contribution to the monthly RR as a ratio
# 	eachMCCtotal = [] 
# 	eachMCCTotalCmpToMth = []
# 	latBandMin = 5.0 #floating point representing the min lat for the region being considered
# 	latBandMax = 20.0 #floating point representing the max lat for the region being considered
# 	lonBandMin = -15.0 #floating point representing the min lon for the region being considered
# 	lonBandMax = 10.0 #floating point representing the max lon for the region being considered	

# 	# these strings are specific to the MERG data
# 	mergVarName = 'ch4'
# 	mergTimeVarName = 'time'
# 	mergLatVarName = 'latitude'
# 	mergLonVarName = 'longitude'

# 	#open a fulldisk merg file to get the full dimensions 
# 	#TODO: find a neater way of doing this
# 	tmp = Nio.open_file("/Users/kimwhitehall/Documents/HU/postDoc/paper/mergNETCDF/merg_2013080923_4km-pixel.nc", format='nc')
	
# 	#clip the lat/lon grid according to user input
# 	#http://www.pyngl.ucar.edu/NioExtendedSelection.shtml
# 	#TODO: figure out how to use netCDF4 to do the clipping tmp = netCDF4.Dataset(filelist[0])
# 	latsraw = tmp.variables[mergLatVarName][:].astype('f2')
# 	lonsraw = tmp.variables[mergLonVarName][:].astype('f2')
# 	lonsraw[lonsraw > 180] = lonsraw[lonsraw > 180] - 360.  # convert to -180,180 if necessary
	
# 	LON, LAT = np.meshgrid(lonsraw, latsraw)
# 	nygrd = len(LAT[:, 0]); nxgrd = len(LON[0, :])
	
# 	#TODO: determine the monthly data file to be opened as opposed to hard coding it
# 	#open the monthly data
# 	TRMMmthData = Dataset(monthlyTRMM,'r',format='NETCDF4')
# 	#convert precip rate mm/hr to monthly value i.e. *(24*31) as Jul in this case
# 	mthlyPrecipRate = (TRMMmthData.variables['pcp'][:,:,:])*24*31
# 	latsrawTRMMData = TRMMmthData.variables['latitude'][:]
# 	lonsrawTRMMData = TRMMmthData.variables['longitude'][:]
# 	lonsrawTRMMData[lonsrawTRMMData > 180] = lonsrawTRMMData[lonsrawTRMMData>180] - 360.
# 	LONTRMM, LATTRMM = np.meshgrid(lonsrawTRMMData, latsrawTRMMData)

# 	nygrdTRMM = len(LATTRMM[:,0]); nxgrdTRMM = len(LONTRMM[0,:])
	
# 	mthlyPrecipRateMasked = ma.masked_array(mthlyPrecipRate, mask=(mthlyPrecipRate < 0.0))
# 	mthlyPrecipRate =[]
	
# 	#regrid the monthly dataset to the MERG grid as the TRMMNETCDFCEs are 4km regridded as well. 
# 	#---------regrid the TRMM data to the MERG dataset ----------------------------------
# 	#regrid using the do_regrid stuff from the Apache OCW 
# 	regriddedmthlyTRMM = ma.zeros((1, nygrd, nxgrd))
# 	#TODO: **ThE PROBLEM **** this regridding is an issue because the regrid occurs only over the lat lons given in the main prog and not
# 	#necessarily the lat lons given for the mthlyprecip domain
# 	#dirty fix: open a full original merg file to get reset the LAT LONS values
# 	regriddedmthlyTRMM = process.do_regrid(mthlyPrecipRateMasked[0,:,:], LATTRMM,  LONTRMM, LAT, LON, order=1, mdi= -999999999)
# 	regriddedTRMM = ma.zeros((regriddedmthlyTRMM.shape))
# 	#----------------------------------------------------------------------------------
# 	#get the lat/lon info for TRMM data (different resolution)
# 	latStartT = find_nearest(latsrawTRMMData, latBandMin)
# 	latEndT = find_nearest(latsrawTRMMData, latBandMax)
# 	lonStartT = find_nearest(lonsrawTRMMData, lonBandMin)
# 	lonEndT = find_nearest(lonsrawTRMMData, lonBandMax)

# 	latStartIndex = np.where(latsrawTRMMData == latStartT)
# 	latEndIndex = np.where(latsrawTRMMData == latEndT)
# 	lonStartIndex = np.where(lonsrawTRMMData == lonStartT)
# 	lonEndIndex = np.where(lonsrawTRMMData == lonEndT)


# 	latStartT = find_nearest(LAT[:,0], latBandMin)
# 	latEndT = find_nearest(LAT[:,0], latBandMax)
# 	lonStartT = find_nearest(LON[0,:], lonBandMin)
# 	lonEndT = find_nearest(LON[0,:], lonBandMax)
# 	latStartIndex = np.where(LAT[:,0] == latStartT)
# 	latEndIndex = np.where(LAT[:,0] == latEndT)
# 	lonStartIndex = np.where(LON[0,:] == lonStartT)
# 	lonEndIndex = np.where(LON[0,:] == lonEndT)
# 	latStartIndexOffset = latStartIndex[0][0]
# 	latEndIndexOffset = latEndIndex[0][0]
# 	lonStartIndexOffset = lonStartIndex[0][0]
# 	lonEndIndexOffset = lonEndIndex[0][0]

# 	#get the relevant TRMM info from the monthly file
# 	mthlyPrecipRate = regriddedmthlyTRMM[latStartIndexOffset:latEndIndexOffset, lonStartIndexOffset:lonEndIndexOffset]
					
# 	TRMMmthData.close()	
		
# 	#we will be using TRMM CE data only
# 	dirName = MAINDIRECTORY+'/TRMMnetcdfCEs'
# 	if not os.path.exists(dirName):
# 		print "Error in the directory"
# 	else:
# 		os.chdir((dirName))
		
# 	for eachlist in MCCListOfLists:
# 		if eachlist:
# 			mccCount +=1
# 			firstTime = True

# 			for eachNode in eachlist:
# 				#determine the filename to check, we will be using TRMM only
# 				cmdLine = 'ls *'+ eachNode + '.nc' #'*.nc'
# 				fileNameCmd = subprocess.Popen(cmdLine, stdout=subprocess.PIPE, shell=True)
# 				#ensure whitespaces at beginning and end are stripped
# 				fileName = (dirName+'/'+fileNameCmd.communicate()[0]).strip()
				
# 				#open file and create accumulation file (compare against the monthly one time too?)
# 				if os.path.exists(fileName):	
# 					#TODO: check if this file belongs to the current mthly TRMM file or, will it belong to the following mth

# 					#open NetCDF file add info to the accu 
# 					TRMMCEData = Dataset(fileName,'r',format='NETCDF4')
# 					precipRate = TRMMCEData.variables['precipitation_Accumulation'][:]
# 					lats = TRMMCEData.variables['latitude'][:]
# 					lons = TRMMCEData.variables['longitude'][:]
# 					lat_min = lats[0]
# 					lat_max = lats[-1]
# 					lon_min = lons[0]
# 					lon_max = lons[-1]

# 					LONTRMM, LATTRMM = np.meshgrid(lons,lats)
# 					nygrdTRMM = len(LATTRMM[:,0]) 
# 					nxgrdTRMM = len(LONTRMM[0,:])
					
# 					precipRate = ma.masked_array(precipRate, mask=(precipRate < 0.0))
# 					TRMMCEData.close()
# 				else:
# 					print "nah dread it aint here"
# 					#TODO: exit elegantly 
# 					sys.exit()
				
# 				if firstTime == True:
# 					#then clip the monthly dataset
# 					#find the min & max lat and lon of the TRMMNETCDF dataset and extract that data from the mthly file
# 					latStartIndex = np.where(LAT[:,0]==LATTRMM[0][0])[0][0]
# 					latEndIndex = np.where(LAT[:,0]==LATTRMM[-1][0])[0][0]
# 					lonStartIndex = np.where(LON[0,:]==LONTRMM[0][0])[0][0]
# 					lonEndIndex = np.where(LON[0,:]==LONTRMM[0][-1])[0][0]
# 					accuPrecipRate = ma.zeros((precipRate.shape))
# 					firstTime = False
# 				else:
# 					accuPrecipRate += precipRate
	
# 				#create new netCDF file to write the accumulated RR associated with the MCC
# 				#can remove here for checking purposes
# 				accuMCCFile = MAINDIRECTORY+'/TRMMnetcdfCEs/accuMCC'+str(mccCount)+'.nc'	
# 				accuMCCData = Dataset(accuMCCFile, 'w', format='NETCDF4')
# 				accuMCCData.description =  'Accumulated precipitation data'
# 				accuMCCData.calendar = 'standard'
# 				accuMCCData.conventions = 'COARDS'
# 				# dimensions
# 				accuMCCData.createDimension('time', None)
# 				accuMCCData.createDimension('lat', nygrdTRMM)
# 				accuMCCData.createDimension('lon', nxgrdTRMM)
# 				# variables
# 				MCCprecip = ('time','lat', 'lon',)
# 				times = accuMCCData.createVariable('time', 'f8', ('time',))
# 				latitude = accuMCCData.createVariable('latitude', 'f8', ('lat',))
# 				longitude = accuMCCData.createVariable('longitude', 'f8', ('lon',))
# 				rainFallacc = accuMCCData.createVariable('precipitation_Accumulation', 'f8',MCCprecip)
# 				rainFallacc.units = 'mm'

# 				longitude[:] = LONTRMM[0,:]
# 				longitude.units = "degrees_east" 
# 				longitude.long_name = "Longitude" 

# 				latitude[:] =  LATTRMM[:,0]
# 				latitude.units = "degrees_north"
# 				latitude.long_name ="Latitude"

# 				rainFallacc[:] = accuPrecipRate[:]

# 				accuMCCData.close()
# 				#end writing the file
				
# 			regriddedTRMM[latStartIndex:(latEndIndex +1),lonStartIndex:(lonEndIndex+1)] += np.squeeze(accuPrecipRate, axis=0)
			
# 			#append total of that MCC to totalMCCsInMth
# 			eachMCCtotal.append(accuPrecipRate.sum())

# 			#append the % contribution of the MCC to the month total within the domain
# 			eachMCCTotalCmpToMth.append(accuPrecipRate.sum()/regriddedmthlyTRMM[latStartIndex:(latEndIndex +1),lonStartIndex:(lonEndIndex+1)].sum())
	
# 	#leave the clipping until the end
# 	#get the relevant TRMM info 
# 	allMCCsPrecip = regriddedTRMM[latStartIndexOffset:(latEndIndexOffset+1), lonStartIndexOffset:(lonEndIndexOffset+1)]
	
# 	#get the relevant TRMM info from the monthly file
# 	mthlyPrecipRate = regriddedmthlyTRMM[latStartIndexOffset:(latEndIndexOffset+1), lonStartIndexOffset:(lonEndIndexOffset+1)]
	
# 	eachCellContribution = ma.zeros(mthlyPrecipRate.shape)
# 	eachCellContribution = allMCCsPrecip/mthlyPrecipRate
# 	eachContributionLess = ma.masked_array(eachCellContribution, mask=(eachCellContribution >= 1.0))
# 	eachContributionMore = ma.masked_array(eachCellContribution, mask=(eachCellContribution <= 1.0))
	
# 	# generate plot info and create the plots

# 	#viewMthlyTotals(eachCellContribution,latBandMin, latBandMax, lonBandMin, lonBandMax)
# 	title = 'Each MCC contribution to the monthly TRMM total'
# 	imgFilename = MAINDIRECTORY+'/images/MCCContribution.gif'
# 	clevs = np.arange(0,100,5)
# 	infoDict ={'dataset':eachContributionLess*100.0, 'imgFilename':imgFilename, 'title':title,'clevs':clevs, 'latBandMin': latBandMin, 'latBandMax': latBandMax, 'lonBandMin': lonBandMin, 'lonBandMax': lonBandMax}
# 	viewMthlyTotals(infoDict)
# 	#viewMthlyTotals(eachContributionLess*100.0,title, imgFilename, latBandMin, latBandMax, lonBandMin, lonBandMax)
	
# 	title = 'MCC contributions that exceed the monthly TRMM total'
# 	imgFilename = MAINDIRECTORY+'/images/MCCexceedTRMM.gif'	
# 	clevs = np.arange(100,float(np.max(eachContributionMore))*100 + 5,5)
# 	infoDict ={'dataset':eachContributionMore*100.0, 'imgFilename':imgFilename, 'title':title,'clevs':clevs, 'latBandMin': latBandMin, 'latBandMax': latBandMax, 'lonBandMin': lonBandMin, 'lonBandMax': lonBandMax}
# 	viewMthlyTotals(infoDict)
# 	#viewMthlyTotals(eachContributionMore*100.0,title, imgFilename, latBandMin, latBandMax, lonBandMin, lonBandMax)
# #******************************************************************
#
#							PLOTS
#
#******************************************************************
def displaySize(finalMCCList): 
	'''
	Purpose:: 
		To create a figure showing the area verse time for each MCS

	Input:: 
		finalMCCList: a list of list of strings representing the list of nodes representing a MCC
	
	Output:: 
		None

	'''
	timeList =[]
	count=1
	imgFilename=''
	minArea=10000.0
	maxArea=0.0
	eachNode={}

	#for each node in the list, get the area information from the dictionary
	#in the graph and calculate the area

	if finalMCCList:
		for eachMCC in finalMCCList:
			#get the info from the node
			for node in eachMCC:
				eachNode=thisDict(node)
				timeList.append(eachNode['cloudElementTime'])

				if eachNode['cloudElementArea'] < minArea:
					minArea = eachNode['cloudElementArea']
				if eachNode['cloudElementArea'] > maxArea:
					maxArea = eachNode['cloudElementArea']

				
			#sort and remove duplicates 
			timeList=list(set(timeList))
			timeList.sort()
			tdelta = timeList[1] - timeList[0]
			starttime = timeList[0]-tdelta
			endtime = timeList[-1]+tdelta
			timeList.insert(0, starttime)
			timeList.append(endtime)

			#plot info
			plt.close('all')
			title = 'Area distribution of the MCC over somewhere'
			fig=plt.figure(facecolor='white', figsize=(18,10)) #figsize=(10,8))#figsize=(16,12))
			fig,ax = plt.subplots(1, facecolor='white', figsize=(10,10))
			
			#the data
			for node in eachMCC: #for eachNode in eachMCC:
				eachNode=thisDict(node)
				if eachNode['cloudElementArea'] < 80000 : #2400.00:
					ax.plot(eachNode['cloudElementTime'], eachNode['cloudElementArea'],'bo', markersize=10)
				elif eachNode['cloudElementArea'] >= 80000.00 and eachNode['cloudElementArea'] < 160000.00:
					ax.plot(eachNode['cloudElementTime'], eachNode['cloudElementArea'],'yo',markersize=20)
				else:
					ax.plot(eachNode['cloudElementTime'], eachNode['cloudElementArea'],'ro',markersize=30)
				
			#axes and labels
			maxArea += 20000.00
			ax.set_xlim(starttime,endtime)
			ax.set_ylim(minArea,maxArea)
			ax.set_ylabel('Area in km^2', fontsize=12)
			ax.set_title(title)
			ax.fmt_xdata = mdates.DateFormatter('%Y-%m-%d%H:%M:%S')
			fig.autofmt_xdate()
			
			plt.subplots_adjust(bottom=0.2)
			
			imgFilename = MAINDIRECTORY+'/images/'+ str(count)+'MCS.gif'
			plt.savefig(imgFilename, facecolor=fig.get_facecolor(), transparent=True)
			
			#if time in not already in the time list, append it
			timeList=[]
			count += 1
	return 
#******************************************************************
def displayPrecip(finalMCCList): 
	'''
	Purpose:: 
		To create a figure showing the precip rate verse time for each MCS

	Input:: 
		finalMCCList: a list of dictionaries representing a list of nodes representing a MCC

	Output:: None

	'''
	timeList =[]
	oriTimeList=[]
	colorBarTime =[]
	count=1
	imgFilename=''
	TRMMprecipDis =[]
	percentagePrecipitating = []#0.0
	CEArea=[]
	nodes=[]
	xy=[]
	x=[]
	y=[]
	precip = []
	partialArea =[]
	totalSize=0.0

	firstTime = True
	xStart =0.0
	yStart = 0.0

	num_bins = 5

	
	#for each node in the list, get the area information from the dictionary
	#in the graph and calculate the area

	if finalMCCList:
		for eachMCC in finalMCCList:
			#get the info from the node
			for node in eachMCC:
				eachNode=thisDict(node)
				if firstTime == True:
					xStart = eachNode['cloudElementCenter'][1]#lon
					yStart = eachNode['cloudElementCenter'][0]#lat
				timeList.append(eachNode['cloudElementTime'])
				percentagePrecipitating.append((eachNode['TRMMArea']/eachNode['cloudElementArea'])*100.0)
				CEArea.append(eachNode['cloudElementArea'])
				nodes.append(eachNode['uniqueID'])
				# print eachNode['uniqueID'], eachNode['cloudElementCenter'][1], eachNode['cloudElementCenter'][0]
				x.append(eachNode['cloudElementCenter'][1])#-xStart)
				y.append(eachNode['cloudElementCenter'][0])#-yStart)
				
				firstTime= False

			#convert the timeList[] to list of floats
			for i in xrange(len(timeList)): #oriTimeList:
				colorBarTime.append(time.mktime(timeList[i].timetuple()))
			
			totalSize = sum(CEArea)
			partialArea = [(a/totalSize)*30000 for a in CEArea]

			# print "x ", x
			# print "y ", y
			
			#plot info
			plt.close('all')

			title = 'Precipitation distribution of the MCS '
			fig,ax = plt.subplots(1, facecolor='white', figsize=(20,7))

			cmap = cm.jet
			ax.scatter(x, y, s=partialArea,  c= colorBarTime, edgecolors='none', marker='o', cmap =cmap)  
			colorBarTime=[]
			colorBarTime =list(set(timeList))
			colorBarTime.sort()
			cb = colorbar_index(ncolors=len(colorBarTime), nlabels=colorBarTime, cmap = cmap)
			
			#axes and labels
			ax.set_xlabel('Degrees Longtude', fontsize=12)
			ax.set_ylabel('Degrees Latitude', fontsize=12)
			ax.set_title(title)
			ax.grid(True)
			plt.subplots_adjust(bottom=0.2)
			
			for i, txt in enumerate(nodes):
				if CEArea[i] >= 2400.00:
					ax.annotate('%d'%percentagePrecipitating[i]+'%', (x[i],y[i]))
				precip=[]

			imgFilename = MAINDIRECTORY+'/images/MCSprecip'+ str(count)+'.gif'
			plt.savefig(imgFilename, facecolor=fig.get_facecolor(), transparent=True)
			
			#reset for next image
			timeList=[]
			percentagePrecipitating =[]
			CEArea =[]
			x=[]
			y=[]
			colorBarTime=[]
			nodes=[]
			precip=[]
			count += 1
			firstTime = True
	return 
#******************************************************************
def plotPrecipHistograms(finalMCCList):
	'''
	Purpose:: 
		To create plots (histograms) of the each TRMMnetcdfCEs files

	Input:: 
		finalMCCList: a list of dictionaries representing a list of nodes representing a MCC

	Output:: 
		plots
	'''
	num_bins = 5
	precip =[]
	imgFilename = " "
	lastTime =" "
	firstTime = True
	MCScount = 0
	MSClen =0
	thisCount = 0
	totalPrecip=np.zeros((1,137,440))

	#TODO: use try except block instead
	if finalMCCList:

		for eachMCC in finalMCCList:
			firstTime = True
			MCScount +=1
			#totalPrecip=np.zeros((1,137,440))
			totalPrecip=np.zeros((1,413,412))

			#get the info from the node
			for node in eachMCC:
				eachNode=thisDict(node)
				thisTime = eachNode['cloudElementTime']
				MCSlen = len(eachMCC)
				thisCount += 1
				
				#this is the precipitation distribution plot from displayPrecip

				if eachNode['cloudElementArea'] >= 2400.0:
					if (str(thisTime) != lastTime and lastTime != " ") or thisCount == MCSlen:	
						plt.close('all')
						title = 'TRMM precipitation distribution for '+ str(thisTime)
						
						fig,ax = plt.subplots(1, facecolor='white', figsize=(7,5))
					
						n,binsdg = np.histogram(precip, num_bins)
						wid = binsdg[1:] - binsdg[:-1]
						plt.bar(binsdg[:-1], n/float(len(precip)), width=wid)

						#make percentage plot
						formatter = FuncFormatter(to_percent)
						plt.xlim(min(binsdg), max(binsdg))
						ax.set_xticks(binsdg)
						ax.set_xlabel('Precipitation [mm]', fontsize=12)
						ax.set_ylabel('Area', fontsize=12)
						ax.set_title(title)
						# Set the formatter
						plt.gca().yaxis.set_major_formatter(formatter)
						plt.gca().xaxis.set_major_formatter(FormatStrFormatter('%0.0f'))
	    				imgFilename = MAINDIRECTORY+'/images/'+str(thisTime)+eachNode['uniqueID']+'TRMMMCS.gif'
	    				
	    				plt.savefig(imgFilename, transparent=True)
	    				precip =[]
	    				
	    			# ------ NETCDF File get info ------------------------------------
					thisFileName = MAINDIRECTORY+'/TRMMnetcdfCEs/TRMM' + str(thisTime).replace(" ", "_") + eachNode['uniqueID'] +'.nc'
					TRMMData = Dataset(thisFileName,'r', format='NETCDF4')
					precipRate = TRMMData.variables['precipitation_Accumulation'][:,:,:]
					CEprecipRate = precipRate[0,:,:]
					TRMMData.close()
					if firstTime==True:
						totalPrecip=np.zeros((CEprecipRate.shape))
					
					totalPrecip = np.add(totalPrecip, precipRate)
					# ------ End NETCDF File ------------------------------------
					for index, value in np.ndenumerate(CEprecipRate): 
						if value != 0.0:
							precip.append(value)

					lastTime = str(thisTime)
					firstTime = False
				else:
					lastTime = str(thisTime)
					firstTime = False  	
	return 
#******************************************************************
def plotHistogram(aList, aTitle, aLabel):
	'''
	Purpose:: 
		To create plots (histograms) of the data entered in aList

	Input:: 
		aList: the list of floating points representing values for e.g. averageArea, averageDuration, etc.
	    aTitle: a string representing the title and the name of the plot e.g. "Average area [km^2]"
	    aLabel: a string representing the x axis info i.e. the data that is being passed and the units e.g. "Area km^2"

	Output:: 
		plots (gif files)
	'''
	num_bins = 10
	precip =[]
	imgFilename = " "
	lastTime =" "
	firstTime = True
	MCScount = 0
	MSClen =0
	thisCount = 0
	
	#TODO: use try except block instead
	if aList:
		
		fig,ax = plt.subplots(1, facecolor='white', figsize=(7,5))
	
		n,binsdg = np.histogram(aList, num_bins, density=True)
		wid = binsdg[1:] - binsdg[:-1]
		#plt.bar(binsdg[:-1], n/float(len(aList)), width=wid)
		plt.bar(binsdg[:-1], n, width=wid)
		# plt.hist(aList, num_bins, width=wid )


		#make percentage plot
		#formatter = FuncFormatter(to_percent)
		plt.xlim(min(binsdg), max(binsdg))
		ax.set_xticks(binsdg)#, rotation=45)
		ax.set_xlabel(aLabel, fontsize=12)
		ax.set_title(aTitle)

		plt.xticks(rotation =45)
		# Set the formatter
		plt.gca().xaxis.set_major_formatter(FormatStrFormatter('%0.0f'))
		plt.subplots_adjust(bottom=0.2)

		imgFilename = MAINDIRECTORY+'/images/'+aTitle.replace(" ","_")+'.gif'
		plt.savefig(imgFilename, facecolor=fig.get_facecolor(), transparent=True)
				
	return 
#******************************************************************
def plotAccTRMM (finalMCCList):
	'''
	Purpose:: 
		(1) generate a file with the accumulated precipiation for the MCS
		(2) generate the appropriate image using GrADS
		TODO: NB: as the domain changes, will need to change XDEF and YDEF by hand to accomodate the new domain
		TODO: look into getting the info from the NETCDF file

	Input:: 
		finalMCCList: a list of dictionaries representing a list of nodes representing a MCC
  
	Output:: 
		a netcdf file containing the accumulated precip 
		a gif (generated in Grads)
	'''
	os.chdir((MAINDIRECTORY+'/TRMMnetcdfCEs'))
	fname =''
	imgFilename = ''
	firstPartName = ''
	firstTime = True
	replaceExpXDef = ''
	
	#Just incase the X11 server is giving problems
	subprocess.call('export DISPLAY=:0.0', shell=True)

	#generate the file name using MCCTimes
	#if the file name exists, add it to the accTRMM file
	for path in finalMCCList:
		for eachNode in path:
			thisNode = thisDict(eachNode)
			fname = 'TRMM'+ str(thisNode['cloudElementTime']).replace(" ", "_") + thisNode['uniqueID'] +'.nc'
			
			if os.path.isfile(fname):	
				#open NetCDF file add info to the accu 
				#print "opening TRMM file ", fname
				TRMMCEData = Dataset(fname,'r',format='NETCDF4')
				precipRate = TRMMCEData.variables['precipitation_Accumulation'][:]
				lats = TRMMCEData.variables['latitude'][:]
				lons = TRMMCEData.variables['longitude'][:]
				LONTRMM, LATTRMM = np.meshgrid(lons,lats)
				nygrdTRMM = len(LATTRMM[:,0]) 
				nxgrdTRMM = len(LONTRMM[0,:])
				precipRate = ma.masked_array(precipRate, mask=(precipRate < 0.0))
				TRMMCEData.close()

				if firstTime == True:
					firstPartName = str(thisNode['cloudElementTime']).replace(" ", "_")+'-'
					accuPrecipRate = ma.zeros((precipRate.shape))
					firstTime = False

				accuPrecipRate += precipRate

		imgFilename = MAINDIRECTORY+'/images/MCSaccu'+firstPartName+str(thisNode['cloudElementTime']).replace(" ", "_")+'.gif'
        #create new netCDF file
		accuTRMMFile = MAINDIRECTORY+'/TRMMnetcdfCEs/accu'+firstPartName+str(thisNode['cloudElementTime']).replace(" ", "_")+'.nc'
		#write the file
		accuTRMMData = Dataset(accuTRMMFile, 'w', format='NETCDF4')
		accuTRMMData.description =  'Accumulated precipitation data'
		accuTRMMData.calendar = 'standard'
		accuTRMMData.conventions = 'COARDS'
		# dimensions
		accuTRMMData.createDimension('time', None)
		accuTRMMData.createDimension('lat', nygrdTRMM)
		accuTRMMData.createDimension('lon', nxgrdTRMM)
		
		# variables
		TRMMprecip = ('time','lat', 'lon',)
		times = accuTRMMData.createVariable('time', 'f8', ('time',))
		times.units = 'hours since '+ str(thisNode['cloudElementTime']).replace(" ", "_")[:-6]
		latitude = accuTRMMData.createVariable('latitude', 'f8', ('lat',))
		longitude = accuTRMMData.createVariable('longitude', 'f8', ('lon',))
		rainFallacc = accuTRMMData.createVariable('precipitation_Accumulation', 'f8',TRMMprecip)
		rainFallacc.units = 'mm'

		longitude[:] = LONTRMM[0,:]
		longitude.units = "degrees_east" 
		longitude.long_name = "Longitude" 

		latitude[:] =  LATTRMM[:,0]
		latitude.units = "degrees_north"
		latitude.long_name ="Latitude"

		rainFallacc[:] = accuPrecipRate[:]

		accuTRMMData.close()

		#generate the image with GrADS
		#print "ny,nx ", nygrdTRMM, nxgrdTRMM, min(lats), max(lats)
		#the ctl file
		subprocess.call('rm acc.ctl', shell=True)
		subprocess.call('touch acc.ctl', shell=True)
		replaceExpDset = 'echo DSET ' + accuTRMMFile +' >> acc.ctl'
		subprocess.call(replaceExpDset, shell=True)  
		subprocess.call('echo "OPTIONS yrev little_endian template" >> acc.ctl', shell=True)
		subprocess.call('echo "DTYPE netcdf" >> acc.ctl', shell=True)
		subprocess.call('echo "UNDEF  0" >> acc.ctl', shell=True)
		subprocess.call('echo "TITLE  TRMM MCS accumulated precipitation" >> acc.ctl', shell=True)
		replaceExpXDef = 'echo XDEF '+ str(nxgrdTRMM) + ' LINEAR ' + str(min(lons)) +' '+ str((max(lons)-min(lons))/nxgrdTRMM) +' >> acc.ctl'
		subprocess.call(replaceExpXDef, shell=True)
		#subprocess.call('echo "XDEF 413 LINEAR  -9.984375 0.036378335 " >> acc.ctl', shell=True)
        #subprocess.call('echo "YDEF 412 LINEAR 5.03515625 0.036378335 " >> acc.ctl', shell=True)
        replaceExpYDef = 'echo YDEF '+str(nygrdTRMM)+' LINEAR '+str(min(lats))+ ' '+str((max(lats)-min(lats))/nygrdTRMM)+' >>acc.ctl'
        subprocess.call(replaceExpYDef, shell=True)
        subprocess.call('echo "ZDEF   01 LEVELS 1" >> acc.ctl', shell=True)
        subprocess.call('echo "TDEF 99999 linear 31aug2009 1hr" >> acc.ctl', shell=True)
        #subprocess.call(replaceExpTdef, shell=True)
        subprocess.call('echo "VARS 1" >> acc.ctl', shell=True)
        subprocess.call('echo "precipitation_Accumulation=>precipAcc     1  t,y,x    precipAccu" >> acc.ctl', shell=True)
        subprocess.call('echo "ENDVARS" >> acc.ctl', shell=True)

        #generate GrADS script
        subprocess.call('rm accuTRMM1.gs', shell=True)
        subprocess.call('touch accuTRMM1.gs', shell=True)
        subprocess.call('echo "''\'reinit''\'" >> accuTRMM1.gs', shell=True)
        subprocess.call('echo "''\'open acc.ctl ''\'" >> accuTRMM1.gs', shell=True)
        subprocess.call('echo "''\'set grads off''\'" >> accuTRMM1.gs', shell=True)
        subprocess.call('echo "''\'set mpdset hires''\'" >> accuTRMM1.gs', shell=True)
        subprocess.call('echo "''\'set gxout shaded''\'" >> accuTRMM1.gs', shell=True)
        subprocess.call('echo "''\'set datawarn off''\'" >> accuTRMM1.gs', shell=True)
        subprocess.call('echo "''\'d precipacc''\'" >> accuTRMM1.gs', shell=True)
        subprocess.call('echo "''\'draw title TRMM Accumulated Precipitation [mm]''\'" >> accuTRMM1.gs', shell=True)
        subprocess.call('echo "''\'run cbarn''\'" >> accuTRMM1.gs', shell=True)
        subprocess.call('echo "''\'printim '+imgFilename +' x1000 y800 white''\'" >> accuTRMM1.gs', shell=True)
        subprocess.call('echo "''\'quit''\'" >> accuTRMM1.gs', shell=True)
        gradscmd = 'grads -blc ' + '\'run accuTRMM1.gs''\''
        subprocess.call(gradscmd, shell=True)
        sys.exit()

        #clean up
        subprocess.call('rm accuTRMM1.gs', shell=True)
        subprocess.call('rm acc.ctl', shell=True)
	
	return	
#******************************************************************
def plotAccuInTimeRange(starttime, endtime):
	'''
	Purpose:: 
		Create accumulated precip plot within a time range given using all CEs

	Input:: 
		starttime: a string representing the time to start the accumulations format yyyy-mm-dd_hh:mm:ss
		endtime: a string representing the time to end the accumulations format yyyy-mm-dd_hh:mm:ss

	Output:: 
		a netcdf file containing the accumulated precip for specified times
		a gif (generated in Grads)

	TODO: pass of pick up from the NETCDF file the  lat, lon and resolution for generating the ctl file
	'''

	os.chdir((MAINDIRECTORY+'/TRMMnetcdfCEs/'))
	#Just incase the X11 server is giving problems
	subprocess.call('export DISPLAY=:0.0', shell=True)

	imgFilename = ''
	firstPartName = ''
	firstTime = True

	fileList = []
	sTime = datetime.strptime(starttime.replace("_"," "),'%Y-%m-%d %H:%M:%S')
	eTime = datetime.strptime(endtime.replace("_"," "),'%Y-%m-%d %H:%M:%S')
	thisTime = sTime

	while thisTime <= eTime:
		fileList = filter(os.path.isfile, glob.glob(('TRMM'+ str(thisTime).replace(" ", "_") + '*' +'.nc')))
		for fname in fileList:
			TRMMCEData = Dataset(fname,'r',format='NETCDF4')
			precipRate = TRMMCEData.variables['precipitation_Accumulation'][:]
			lats = TRMMCEData.variables['latitude'][:]
			lons = TRMMCEData.variables['longitude'][:]
			LONTRMM, LATTRMM = np.meshgrid(lons,lats)
			nygrdTRMM = len(LATTRMM[:,0]) 
			nxgrdTRMM = len(LONTRMM[0,:])
			precipRate = ma.masked_array(precipRate, mask=(precipRate < 0.0))
			TRMMCEData.close()

			if firstTime == True:
				accuPrecipRate = ma.zeros((precipRate.shape))
				firstTime = False

			accuPrecipRate += precipRate

		#increment the time
		thisTime +=timedelta(hours=TRES)

	#create new netCDF file
	accuTRMMFile = MAINDIRECTORY+'/TRMMnetcdfCEs/accu'+starttime+'-'+endtime+'.nc'
	print "accuTRMMFile ", accuTRMMFile
	#write the file
	accuTRMMData = Dataset(accuTRMMFile, 'w', format='NETCDF4')
	accuTRMMData.description =  'Accumulated precipitation data'
	accuTRMMData.calendar = 'standard'
	accuTRMMData.conventions = 'COARDS'
	# dimensions
	accuTRMMData.createDimension('time', None)
	accuTRMMData.createDimension('lat', nygrdTRMM)
	accuTRMMData.createDimension('lon', nxgrdTRMM)
	
	# variables
	TRMMprecip = ('time','lat', 'lon',)
	times = accuTRMMData.createVariable('time', 'f8', ('time',))
	times.units = 'hours since '+ starttime[:-6]
	latitude = accuTRMMData.createVariable('latitude', 'f8', ('lat',))
	longitude = accuTRMMData.createVariable('longitude', 'f8', ('lon',))
	rainFallacc = accuTRMMData.createVariable('precipitation_Accumulation', 'f8',TRMMprecip)
	rainFallacc.units = 'mm'

	longitude[:] = LONTRMM[0,:]
	longitude.units = "degrees_east" 
	longitude.long_name = "Longitude" 

	latitude[:] =  LATTRMM[:,0]
	latitude.units = "degrees_north"
	latitude.long_name ="Latitude"

	rainFallacc[:] = accuPrecipRate[:]

	accuTRMMData.close()

	#generate the image with GrADS
	#the ctl file
	subprocess.call('rm acc.ctl', shell=True)
	subprocess.call('touch acc.ctl', shell=True)
	replaceExpDset = 'echo DSET ' + accuTRMMFile +' >> acc.ctl'
	subprocess.call(replaceExpDset, shell=True)  
	subprocess.call('echo "OPTIONS yrev little_endian template" >> acc.ctl', shell=True)
	subprocess.call('echo "DTYPE netcdf" >> acc.ctl', shell=True)
	subprocess.call('echo "UNDEF  0" >> acc.ctl', shell=True)
	subprocess.call('echo "TITLE  TRMM MCS accumulated precipitation" >> acc.ctl', shell=True)
	replaceExpXDef = 'echo XDEF '+ str(nxgrdTRMM) + ' LINEAR ' + str(min(lons)) +' '+ str((max(lons)-min(lons))/nxgrdTRMM) +' >> acc.ctl'
	subprocess.call(replaceExpXDef, shell=True)
	replaceExpYDef = 'echo YDEF '+str(nygrdTRMM)+' LINEAR '+str(min(lats))+ ' '+str((max(lats)-min(lats))/nygrdTRMM)+' >>acc.ctl'
	subprocess.call(replaceExpYDef, shell=True)
	#subprocess.call('echo "XDEF 384 LINEAR  -8.96875 0.036378335 " >> acc.ctl', shell=True)
	#subprocess.call('echo "YDEF 384 LINEAR 5.03515625 0.036378335 " >> acc.ctl', shell=True)
	subprocess.call('echo "ZDEF   01 LEVELS 1" >> acc.ctl', shell=True)
	subprocess.call('echo "TDEF 99999 linear 31aug2009 1hr" >> acc.ctl', shell=True)
	subprocess.call('echo "VARS 1" >> acc.ctl', shell=True)
	subprocess.call('echo "precipitation_Accumulation=>precipAcc     1  t,y,x    precipAccu" >> acc.ctl', shell=True)
	subprocess.call('echo "ENDVARS" >> acc.ctl', shell=True)
	#generate GrADS script
	imgFilename = MAINDIRECTORY+'/images/accu'+starttime+'-'+endtime+'.gif'
	subprocess.call('rm accuTRMM1.gs', shell=True)
	subprocess.call('touch accuTRMM1.gs', shell=True)
	subprocess.call('echo "''\'reinit''\'" >> accuTRMM1.gs', shell=True)
	subprocess.call('echo "''\'open acc.ctl ''\'" >> accuTRMM1.gs', shell=True)
	subprocess.call('echo "''\'set grads off''\'" >> accuTRMM1.gs', shell=True)
	subprocess.call('echo "''\'set mpdset hires''\'" >> accuTRMM1.gs', shell=True)
	subprocess.call('echo "''\'set gxout shaded''\'" >> accuTRMM1.gs', shell=True)
	subprocess.call('echo "''\'set datawarn off''\'" >> accuTRMM1.gs', shell=True)
	subprocess.call('echo "''\'d precipacc''\'" >> accuTRMM1.gs', shell=True)
	subprocess.call('echo "''\'draw title TRMM Accumulated Precipitation [mm]''\'" >> accuTRMM1.gs', shell=True)
	subprocess.call('echo "''\'run cbarn''\'" >> accuTRMM1.gs', shell=True)
	subprocess.call('echo "''\'printim '+imgFilename +' x1000 y800 white''\'" >> accuTRMM1.gs', shell=True)
	subprocess.call('echo "''\'quit''\'" >> accuTRMM1.gs', shell=True)
	gradscmd = 'grads -blc ' + '\'run accuTRMM1.gs''\''
	subprocess.call(gradscmd, shell=True)

	#clean up
	subprocess.call('rm accuTRMM1.gs', shell=True)
	subprocess.call('rm acc.ctl', shell=True)

	return	
#******************************************************************
def createTextFile(finalMCCList, identifier):
	'''
	Purpose:: 
		Create a text file with information about the MCS
		This function is expected to be especially of use regarding long term record checks

	Input:: 
		finalMCCList: a list of dictionaries representing a list of nodes representing a MCC
		identifier: an integer representing the type of list that has been entered...this is for creating file purposes
			1 - MCCList; 2- MCSList

	Output:: 
		a user readable text file with all information about each MCS
		a user readable text file with the summary of the MCS

	Assumptions:: 
	'''

	durations=0.0
	startTimes =[]
	endTimes=[]
	averagePropagationSpeed = 0.0
	speedCounter = 0
	maxArea =0.0
	amax = 0.0
	avgMaxArea =[]
	maxAreaCounter =0.0
	maxAreaTime=''
	eccentricity = 0.0
	firstTime = True
	matureFlag = True
	timeMCSMatures=''
	maxCEprecipRate = 0.0
	minCEprecipRate = 0.0
	averageArea = 0.0
	averageAreaCounter = 0
	durationOfMatureMCC = 0
	avgMaxPrecipRate = 0.0
	avgMaxPrecipRateCounter = 0
	avgMinPrecipRate = 0.0
	avgMinPrecipRateCounter = 0
	CEspeed = 0.0
	MCSspeed = 0.0
	MCSspeedCounter = 0
	MCSPrecipTotal = 0.0
	avgMCSPrecipTotalCounter = 0
	bigPtotal = 0.0
	bigPtotalCounter = 0
	allPropagationSpeeds =[]
	averageAreas =[]
	areaAvg = 0.0
	avgPrecipTotal = 0.0
	avgPrecipTotalCounter = 0
	avgMaxMCSPrecipRate = 0.0
	avgMaxMCSPrecipRateCounter = 0
	avgMinMCSPrecipRate = 0.0
	avgMinMCSPrecipRateCounter = 0
	minMax =[]
	avgPrecipArea = []
	location =[]
	avgPrecipAreaPercent = 0.0
	precipArea = 0.0
	precipAreaPercent = 0.0
	precipPercent =[]
	precipCounter = 0
	precipAreaAvg = 0.0
	minSpeed = 0.0
	maxSpeed =0.0

	if identifier == 1:
		MCSUserFile = open((MAINDIRECTORY+'/textFiles/MCCsUserFile.txt'),'wb')
		MCSSummaryFile = open((MAINDIRECTORY+'/textFiles/MCCSummary.txt'),'wb')
		MCSPostFile = open((MAINDIRECTORY+'/textFiles/MCCPostPrecessing.txt'),'wb')
	
	if identifier == 2:
		MCSUserFile = open((MAINDIRECTORY+'/textFiles/MCSsUserFile.txt'),'wb')
		MCSSummaryFile = open((MAINDIRECTORY+'/textFiles/MCSSummary.txt'),'wb')
		MCSPostFile = open((MAINDIRECTORY+'/textFiles/MCSPostPrecessing.txt'),'wb')

	for eachPath in finalMCCList:
		eachPath.sort(key=lambda nodeID:(len(nodeID.split('C')[0]), nodeID.split('C')[0], nodeID.split('CE')[1]))
		MCSPostFile.write("\n %s" %eachPath)

		startTime = thisDict(eachPath[0])['cloudElementTime']
		endTime = thisDict(eachPath[-1])['cloudElementTime']
		duration = (endTime - startTime) + timedelta(hours=TRES)
		
		# convert datatime duration to seconds and add to the total for the average duration of all MCS in finalMCCList
		durations += (duration.total_seconds()) 
		
		#durations += duration
		startTimes.append(startTime)
		endTimes.append(endTime)

		#get the precip info
		
		for eachNode in eachPath:

			thisNode = thisDict(eachNode)

			#set first time min "fake" values
			if firstTime == True:
				minCEprecipRate = thisNode['CETRMMmin']
				avgMinMCSPrecipRate += thisNode['CETRMMmin']
				firstTime = False

			#calculate the speed
			if thisNode['cloudElementArea'] >= OUTER_CLOUD_SHIELD_AREA:
				averagePropagationSpeed += findCESpeed(eachNode, eachPath)
				speedCounter +=1

			#Amax: find max area
			if thisNode['cloudElementArea'] > maxArea:
				maxArea = thisNode['cloudElementArea']
				maxAreaTime = str(thisNode['cloudElementTime'])
				eccentricity = thisNode['cloudElementEccentricity']
				location = thisNode['cloudElementCenter']
				
				#determine the time the feature matures
				if matureFlag == True:
					timeMCSMatures = str(thisNode['cloudElementTime'])
					matureFlag = False

			#find min and max precip rate 
			if thisNode['CETRMMmin'] < minCEprecipRate:
				minCEprecipRate = thisNode['CETRMMmin']
		
			if thisNode['CETRMMmax'] > maxCEprecipRate:
				maxCEprecipRate = thisNode['CETRMMmax']
				

			#calculations for only the mature stage 
			#for MCS nodes, this may throw an error as all the nodes would have been read to be given an identifier
			if thisNode['nodeMCSIdentifier'] == 'M':
				#calculate average area of the maturity feature only 
				averageArea += thisNode['cloudElementArea']
				averageAreaCounter += 1
				durationOfMatureMCC +=1
				avgMaxPrecipRate += thisNode['CETRMMmax']
				avgMaxPrecipRateCounter += 1
				avgMinPrecipRate += thisNode['CETRMMmin']
				avgMinPrecipRateCounter += 1
				avgMaxMCSPrecipRate += thisNode['CETRMMmax']
				avgMaxMCSPrecipRateCounter += 1
				avgMinMCSPrecipRate += thisNode['CETRMMmin']
				avgMinMCSPrecipRateCounter += 1

				#the precip percentage (TRMM area/CE area)
				if thisNode['cloudElementArea'] >= 0.0 and thisNode['TRMMArea'] >= 0.0:
					precipArea += thisNode['TRMMArea']
					avgPrecipArea.append(thisNode['TRMMArea'])
					avgPrecipAreaPercent += (thisNode['TRMMArea']/thisNode['cloudElementArea'])
					precipPercent.append((thisNode['TRMMArea']/thisNode['cloudElementArea'])) 
					precipCounter += 1

				#system speed for only mature stage
				CEspeed = findCESpeed(eachNode,eachPath)
				if CEspeed > 0.0 :
					MCSspeed += CEspeed
					MCSspeedCounter += 1
					
			#find accumulated precip
			if thisNode['cloudElementPrecipTotal'] > 0.0:
				MCSPrecipTotal += thisNode['cloudElementPrecipTotal']
				avgMCSPrecipTotalCounter +=1

		#A: calculate the average Area of the (mature) MCS
		if averageAreaCounter > 0: # and averageAreaCounter > 0:
			averageArea/= averageAreaCounter
			averageAreas.append(averageArea)

		#v: MCS speed 
		if MCSspeedCounter > 0: # and MCSspeed > 0.0:
			MCSspeed /= MCSspeedCounter
			
		#smallP_max: calculate the average max precip rate (mm/h)
		if avgMaxMCSPrecipRateCounter > 0 : #and avgMaxPrecipRate > 0.0:
			avgMaxMCSPrecipRate /= avgMaxMCSPrecipRateCounter
			
		#smallP_min: calculate the average min precip rate (mm/h)
		if avgMinMCSPrecipRateCounter > 0 : #and avgMinPrecipRate > 0.0:
			avgMinMCSPrecipRate /= avgMinMCSPrecipRateCounter
			
		#smallP_avg: calculate the average precipitation (mm hr-1)
		if MCSPrecipTotal > 0.0: # and avgMCSPrecipTotalCounter> 0:
			avgMCSPrecipTotal = MCSPrecipTotal/avgMCSPrecipTotalCounter
			avgPrecipTotal += avgMCSPrecipTotal
			avgPrecipTotalCounter += 1
			
		#smallP_total = MCSPrecipTotal
		#precip over the MCS lifetime prep for bigP_total
		if MCSPrecipTotal > 0.0: 
			bigPtotal += MCSPrecipTotal
			bigPtotalCounter += 1
			
		if maxArea > 0.0:
			avgMaxArea.append(maxArea)
			maxAreaCounter += 1

		#verage precipate area precentage (TRMM/CE area)
		if precipCounter > 0:
			avgPrecipAreaPercent /= precipCounter
			precipArea /= precipCounter


		#write stuff to file
		MCSUserFile.write("\n\n\nStarttime is: %s " %(str(startTime)))
		MCSUserFile.write("\nEndtime is: %s " %(str(endTime)))
		MCSUserFile.write("\nLife duration is %s hrs" %(str(duration)))
		MCSUserFile.write("\nTime of maturity is %s " %(timeMCSMatures))
		MCSUserFile.write("\nDuration mature stage is: %s " %durationOfMatureMCC*TRES)
		MCSUserFile.write("\nAverage area is: %.4f km^2 " %(averageArea))
		MCSUserFile.write("\nMax area is: %.4f km^2 " %(maxArea))
		MCSUserFile.write("\nMax area time is: %s " %(maxAreaTime))
		MCSUserFile.write("\nEccentricity at max area is: %.4f " %(eccentricity))
		MCSUserFile.write("\nCenter (lat,lon) at max area is: %.2f\t%.2f" %(location[0], location[1]))
		MCSUserFile.write("\nPropagation speed is %.4f " %(MCSspeed))
		MCSUserFile.write("\nMCS minimum preicip rate is %.4f mmh^-1" %(minCEprecipRate))
		MCSUserFile.write("\nMCS maximum preicip rate is %.4f mmh^-1" %(maxCEprecipRate))
		MCSUserFile.write("\nTotal precipitation during MCS is %.4f mm/lifetime" %(MCSPrecipTotal))
		MCSUserFile.write("\nAverage MCS precipitation is %.4f mm" %(avgMCSPrecipTotal))
		MCSUserFile.write("\nAverage MCS maximum precipitation is %.4f mmh^-1" %(avgMaxMCSPrecipRate))
		MCSUserFile.write("\nAverage MCS minimum precipitation is %.4f mmh^-1" %(avgMinMCSPrecipRate))
		MCSUserFile.write("\nAverage precipitation area is %.4f km^2 " %(precipArea))
		MCSUserFile.write("\nPrecipitation area percentage of mature system %.4f percent " %(avgPrecipAreaPercent*100))


		#append stuff to lists for the summary file
		if MCSspeed > 0.0:
			allPropagationSpeeds.append(MCSspeed)
			averagePropagationSpeed += MCSspeed
			speedCounter += 1

		#reset vars for next MCS in list
		aaveragePropagationSpeed = 0.0
		averageArea = 0.0
		averageAreaCounter = 0
		durationOfMatureMCC = 0
		MCSspeed = 0.0
		MCSspeedCounter = 0
		MCSPrecipTotal = 0.0
		avgMaxMCSPrecipRate =0.0
		avgMaxMCSPrecipRateCounter = 0
		avgMinMCSPrecipRate = 0.0
		avgMinMCSPrecipRateCounter = 0
		firstTime = True
		matureFlag = True
		avgMCSPrecipTotalCounter=0
		avgPrecipAreaPercent = 0.0
		precipArea = 0.0
		precipCounter = 0
		maxArea = 0.0
		maxAreaTime=''
		eccentricity = 0.0
		timeMCSMatures=''
		maxCEprecipRate = 0.0
		minCEprecipRate = 0.0
		location =[]

	#LD: average duration
	if len(finalMCCList) > 1:
		durations /= len(finalMCCList)
		durations /= 3600.0 #convert to hours
	
		#A: average area
		areaAvg = sum(averageAreas)/ len(finalMCCList)
	#create histogram plot here
	if len(averageAreas) > 1:
		plotHistogram(averageAreas, "Average Area [km^2]", "Area [km^2]")

	#Amax: average maximum area
	if maxAreaCounter > 0.0: #and avgMaxArea > 0.0 : 
		amax = sum(avgMaxArea)/ maxAreaCounter
		#create histogram plot here
		if len(avgMaxArea) > 1:
			plotHistogram(avgMaxArea, "Maximum Area [km^2]", "Area [km^2]")

	#v_avg: calculate the average propagation speed 
	if speedCounter > 0 :  # and averagePropagationSpeed > 0.0
		averagePropagationSpeed /= speedCounter
	
	#bigP_min: calculate the min rate in mature system
	if avgMinPrecipRate >  0.0: # and avgMinPrecipRateCounter > 0.0:
		avgMinPrecipRate /= avgMinPrecipRateCounter

	#bigP_max: calculate the max rate in mature system
	if avgMinPrecipRateCounter > 0.0: #and avgMaxPrecipRate >  0.0: 
		avgMaxPrecipRate /= avgMaxPrecipRateCounter

	#bigP_avg: average total preicip rate mm/hr
	if avgPrecipTotalCounter > 0.0: # and avgPrecipTotal > 0.0: 
		avgPrecipTotal /= avgPrecipTotalCounter

	#bigP_total: total precip rate mm/LD
	if bigPtotalCounter > 0.0: #and bigPtotal > 0.0: 
		bigPtotal /= bigPtotalCounter

	#precipitation area percentage
	if len(precipPercent) > 0:
		precipAreaPercent = (sum(precipPercent)/len(precipPercent))*100.0

	#average precipitation area
	if len(avgPrecipArea) > 0:
		precipAreaAvg = sum(avgPrecipArea)/len(avgPrecipArea)
		if len(avgPrecipArea) > 1:
			plotHistogram(avgPrecipArea, "Average Rainfall Area [km^2]", "Area [km^2]")
		

	sTime = str(averageTime(startTimes))
	eTime = str(averageTime(endTimes))
	if len (allPropagationSpeeds) > 1:
		maxSpeed = max(allPropagationSpeeds)
		minSpeed = min(allPropagationSpeeds)
	
	#write stuff to the summary file
	MCSSummaryFile.write("\nNumber of features is %d " %(len(finalMCCList)))
	MCSSummaryFile.write("\nAverage duration is %.4f hrs " %(durations))
	MCSSummaryFile.write("\nAverage startTime is %s " %(sTime[-8:]))
	MCSSummaryFile.write("\nAverage endTime is %s " %(eTime[-8:]))
	MCSSummaryFile.write("\nAverage size is %.4f km^2 " %(areaAvg))
	MCSSummaryFile.write("\nAverage precipitation area is %.4f km^2 " %(precipAreaAvg))
	MCSSummaryFile.write("\nAverage maximum size is %.4f km^2 " %(amax))
	MCSSummaryFile.write("\nAverage propagation speed is %.4f ms^-1" %(averagePropagationSpeed))
	MCSSummaryFile.write("\nMaximum propagation speed is %.4f ms^-1 " %(maxSpeed))
	MCSSummaryFile.write("\nMinimum propagation speed is %.4f ms^-1 " %(minSpeed))
	MCSSummaryFile.write("\nAverage minimum precipitation rate is %.4f mmh^-1" %(avgMinPrecipRate))
	MCSSummaryFile.write("\nAverage maximum precipitation rate is %.4f mm h^-1" %(avgMaxPrecipRate))
	MCSSummaryFile.write("\nAverage precipitation is %.4f mm h^-1 " %(avgPrecipTotal))
	MCSSummaryFile.write("\nAverage total precipitation during MCSs is %.4f mm/LD " %(bigPtotal))
	MCSSummaryFile.write("\nAverage precipitation area percentage is %.4f percent " %(precipAreaPercent))


	MCSUserFile.close
	MCSSummaryFile.close
	MCSPostFile.close
	return
#******************************************************************
def viewMthlyTotals(plotInfoDict):
	'''
	Purpose:: 
		To display the percentage contribution of each MCC to the monthly total
	Input:: 
		plotInfoDict: a dictionary containing all the information needed for plotting
			dataset: 4D numpy array of data to be plotted
			title: string representing the title to be used in the plt
			imgFilename: a string representing the file name to be used to save the plt
			clevs: an array representing the values and the interval for the legend
			latBandMin: floating-point number representing the minimum latitude in the domain
			latBandMax: floating-point number representing the maximum latitude in the domain
			lonBandMin: floating-point number representing the minimum longitude in the domain
			lonBandMax: floating-point number representing the maximum longitude in the domain
		
	Output:: 
		a plot

	Assumptions:: uses Matplotlib

	'''
	plt.close('all')

	Basemap.latlon_default=True
	
	a_map = Basemap(projection = 'merc', llcrnrlon = plotInfoDict['lonBandMin'], 
			urcrnrlon = plotInfoDict['lonBandMax'], llcrnrlat = plotInfoDict['latBandMin'], urcrnrlat = plotInfoDict['latBandMax'], resolution = 'l')

	a_map.drawcoastlines(linewidth = 0.25)
	a_map.drawcountries(linewidth = 0.25)

	nygrd = plotInfoDict['dataset'].shape[0]; nxgrd = plotInfoDict['dataset'].shape[1]	
	
	#projecting on to the correct map grid
	lons, lats = a_map.makegrid(nxgrd, nygrd)
	x,y = a_map(lons, lats)
	
	#actually print the map
	cs = a_map.contourf(x,y,plotInfoDict['dataset'],plotInfoDict['clevs'], cmap = plt.cm.Blues)#PuRd)
	
	cbar = a_map.colorbar(cs, location = 'bottom')#, pad = "5%")
	cbar.set_label('%')

	plt.hold(True)

	plt.title(plotInfoDict['title'])
	    				
	plt.savefig(plotInfoDict['imgFilename'])#, transparent = True)
#******************************************************************
#******************************************************************
#			PLOTTING UTIL SCRIPTS
#******************************************************************
def to_percent(y,position):
	'''
	Purpose:: 
		Utility script for generating the y-axis for plots
	'''
	return (str(100*y)+'%')
#******************************************************************
def colorbar_index(ncolors, nlabels, cmap):
	'''
	Purpose:: 
		Utility script for crating a colorbar
		Taken from http://stackoverflow.com/questions/18704353/correcting-matplotlib-colorbar-ticks
	'''
	cmap = cmap_discretize(cmap, ncolors)
	mappable = cm.ScalarMappable(cmap=cmap)
	mappable.set_array([])
	mappable.set_clim(-0.5, ncolors+0.5)
	colorbar = plt.colorbar(mappable)#, orientation='horizontal')
	colorbar.set_ticks(np.linspace(0, ncolors, ncolors))
	colorbar.set_ticklabels(nlabels)
	return
#******************************************************************
def cmap_discretize(cmap, N):
    '''
    Taken from: http://stackoverflow.com/questions/18704353/correcting-matplotlib-colorbar-ticks
    http://wiki.scipy.org/Cookbook/Matplotlib/ColormapTransformations
    Return a discrete colormap from the continuous colormap cmap.

        cmap: colormap instance, eg. cm.jet. 
        N: number of colors.

    Example
        x = resize(arange(100), (5,100))
        djet = cmap_discretize(cm.jet, 5)
        imshow(x, cmap=djet)
    '''

    if type(cmap) == str:
        cmap = plt.get_cmap(cmap)
    colors_i = np.concatenate((np.linspace(0, 1., N), (0.,0.,0.,0.)))
    colors_rgba = cmap(colors_i)
    indices = np.linspace(0, 1., N+1)
    cdict = {}
    for ki,key in enumerate(('red','green','blue')):
        cdict[key] = [ (indices[i], colors_rgba[i-1,ki], colors_rgba[i,ki])
                       for i in xrange(N+1) ]
    # Return colormap object.
    return mcolors.LinearSegmentedColormap(cmap.name + "_%d"%N, cdict, 1024)
#******************************************************************


			

