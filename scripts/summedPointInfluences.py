# ---------------------------------------------------------------------------
# THIS SCRIPT IS A BETA RELEASE. USE AT YOUR OWN RISK, AND SEND FEEDBACK TO kfisher@wcs.org.
# summedPointInfluences.py
# Kim Fisher (kfisher@wcs.org) and Karl Didier (kdidier@wcs.org)
# Script for ArcGIS tool to calculate an index of influence intensity (e.g., hunting) from multiple features (e.g., villages) using a cost surface (e.g., travel time).
# The features can be weighted (e.g., by population size), and the result is expressed in weight (e.g. hunter population) and can be converted to integer.
# Based loosely on original AML by Gosia Bryja (gbrya@wcs.org) and Karl Didier (kdidier@wcs.org).
# Requirements: ArcView or greater license; Spatial Analyst
# 0.1 KF 08.23.10 Basic script
# 0.2 KF 09.19.10 Basic error trapping, bug fixes, documentation. Commented lines making normalization optional.
# 0.3 KF 09.23.10 Exception handling 2.6-compliant. Handle output path spaces. Add upper-limit cost parameter (maximum travel time).
#                 Change to central loop logic to produce cell values in weight (hunters)/cell. 
#                 Save out each intermediate grid and add at the end, to allow for debugging and future multicore processing.
# 0.4 KF 10.05.10 Fixed 9.3 bug, misc. other bugs.
# 0.5 KF 10.21.10 Restructure normalization for pre-influence; use max of all costdist maxes when no costdist max specified.
#                 New parameter: intermediate grids dropdown: Zip, Retain, and Delete, with Zip as default
#                 Can now specify ArcMap layers for input datasets. Improved performance. Various bug fixes.
# 0.6 KF 07.08.11 Deal with special chars from layer names; fixed costInput rather than cost used; handle img input and output; output regex check;
#                 handle gdb output location; handle existing outputs; select by attrib rather than select; accept polygons as well as points;
#                 removed equal weight control; various bug fixes
# 0.7 KF 08.14.11 Created addRastersFromIDs(gp, prefix, feats, outputRaster) to handle crashing from adding too many individual rasters.
#                 Added checks for linear projections and disk space. Documentation draft.
# 1.0 beta KF 12.24.11 Misc cosmetic changes. Finished documentation.
# 1.0 beta 2 KF 1.4.13 Fixed: gp.Sample() with in_memory caused unknown error; changed to write to disc.
#
# Todo: fix: , vs . decimal separator causes failure
# Todo: fix file-access issues on Windows 7
# Todo: setprogressor functions not working the same in 9.3 and 10?
# Todo: intermittent: crash during zip operation?
# Todo: intermittent: no sa extension available after running spi?
# Todo 2: option of using cost back link to incorporate slope direction into cost (ie uphill higher cost than downhill)
# Todo 2: user choice of normalization functions
# Todo 2: arcpy version?
# ---------------------------------------------------------------------------


try:

## SETUP ##
   
   import arcgisscripting, os, re, time, utilities as util, spiExceptions as spie
   gp = arcgisscripting.create(9.3)
   gp.overWriteOutput = 1
   if gp.CheckExtension("spatial") != "Available": raise spie.spiException("LicenseError", gp)
   gp.CheckOutExtension("spatial")
   gp.pyramid = "PYRAMIDS 0"
   gp.rasterStatistics = "NONE"

## INPUTS ##

   costInput = gp.Describe(gp.GetParameterAsText(0)).CatalogPath   # C:\_data\ChangTang\summedPointInfluence\cost_surf or raster layer
                                                                   # use source of layer, if provided; makes sure bad chars in layer name don't interfere
   maxCostDistance = gp.GetParameter(1)                            # 1440 (e.g. minutes)
   featsInput = gp.GetParameterAsText(2)                           # C:\_data\ChangTang\summedPointInfluence\towns3.shp or feature layer
                                                                   # do not use source of layer: respect selection if any
   weightColumn = gp.GetParameterAsText(3)                         # pop
   equalWeight = True
   if weightColumn != "": equalWeight = False
   outGrid = gp.GetParameterAsText(4)                              # C:\_data\ChangTang\summedPointInfluence\output\spi
   convertToInteger = gp.GetParameter(5)                           # True|False
   intermediateOutput = gp.GetParameterAsText(6)                   # Zip, Retain, or Delete, with Zip as default

## VALIDATION ##
   # Since restructuring normalization, some of these checks may no longer be strictly necessary. However, I'm leaving them in for now
   # because they're still pretty good guidelines for what will take the script a prohibitively long time.

   gp.Extent = gp.Mask = gp.snapRaster = costInput
   gp.Cellsize = float(gp.GetRasterProperties(costInput, "CELLSIZEX").GetOutput(0))
   
   # Make sure input datasets are in projected coordinate systems
   if (gp.Describe(costInput).spatialReference.linearUnitName == ''): raise spie.spiException("ProjectionError", gp, costInput)
   if (gp.Describe(featsInput).spatialReference.linearUnitName == ''): raise spie.spiException("ProjectionError", gp, featsInput)
   
   # Don't allow grid to be > ~ 10000 x 10000 cells, or have values <= 0 or > 10000
   colCount = int(gp.GetRasterProperties(costInput, "COLUMNCOUNT").GetOutput(0))
   rowCount = int(gp.GetRasterProperties(costInput, "ROWCOUNT").GetOutput(0))
   if colCount * rowCount > 100000000: raise spie.spiException("CostSizeError", gp)
   if float(gp.GetRasterProperties(costInput, "MINIMUM").GetOutput(0)) <= 0 or float(gp.GetRasterProperties(costInput, "MAXIMUM").GetOutput(0)) > 10000: raise spie.spiException("CostRangeError", gp)
   
   # Don't allow spaces in output path
   if os.path.dirname(outGrid).find(" ") != -1: raise spie.spiException("OutputPathError", gp)
   # Check for special chars in output name
   foundchars = util.badChars(outGrid)
   if len(foundchars) > 0: raise spie.spiException("OutputNameBadCharsError", gp, foundchars)
   # Also check for grid names too long
   if os.path.basename(outGrid).find(".") == -1 and len(os.path.basename(outGrid)) > 13: raise spie.spiException("OutputNameLengthError", gp)
   
   # Don't allow > 1000 features
   featsCount = int(gp.GetCount(featsInput).GetOutput(0))
   if featsCount <= 0 or featsCount > 1000: raise spie.spiException("FeatRangeError", gp)
   gp.SetProgressor("step", "Initializing...", 0, (featsCount * 2) + 1, 1)
   
   # Make a stab at assuring there's enough disk space
   costDiskSize = colCount * rowCount * util.getRasterBytes(costInput, gp) #* int(gp.GetRasterProperties(costInput, "BANDCOUNT").GetOutput(0))
   diskSpaceAvail = util.getFreeSpace(costInput)
   # Lots could potentially go wrong in these with the above two functions. Possible errors: costDiskSize = -1; diskSpaceAvail = 0
   if costDiskSize * (featsCount + 4) >= diskSpaceAvail and diskSpaceAvail != 0: raise spie.spiException("DiskSpaceError", gp, [costDiskSize * (featsCount + 4), diskSpaceAvail])

   # Ensure unique id field
   if gp.Describe(featsInput).OIDFieldName == None: raise spie.spiException("OIDError", gp)
      
   # Limit weight mean to 100000
   if equalWeight != True:
      if util.getFieldMean(featsInput, weightColumn, featsCount, gp) > 100000: raise spie.spiException("WeightRangeError", gp)

   # Make sure all feats are sitting in cost cells with values
   noDataFeats = util.getNoDataFeatures(costInput, featsInput, gp)
   #gp.AddMessage("noDataFeats: " + str(noDataFeats))
   if len(noDataFeats) > 0: raise spie.spiException("NoDataFeatsError", gp, [str(noDataFeats)])

## INITIALIZATION ##
   
   feats = "featslyr"             # name of intermediate feats layer
   cost = "cost"                  # name of intermediate cost surface (path = dirWorking)
   costDist = "cd"                # basename of cost-distance grid for each loop
   influence = "infl"             # basename of influence grid for each feat
   dirWorkingName = "SPIworking"  # name of working subdirectory, for constructing dirWorking and zipf
   
   # Create our own workspace based on output dir, because default system temp, e.g. C:/DOCUME~1/kfisher/LOCALS~1/Temp/
   # fails in SingleOutputMapAlgebra() because ~ chars are stripped out
   # Note this definition assumes tool parameter for outGrid is defined as "output" and raster dataset
   # If output location is gdb, create dirWorking one level up
   #gp.AddMessage("workspace type: " + gp.Describe(os.path.dirname(outGrid)).workspaceType)
   dirWorkingContainer = os.path.dirname(os.path.dirname(outGrid))
   if gp.Describe(os.path.dirname(outGrid)).workspaceType == "FileSystem": dirWorkingContainer = os.path.dirname(outGrid)
   dirWorkingName = util.overwriteSafeName(dirWorkingContainer, dirWorkingName)
   dirWorking = dirWorkingContainer + os.sep + dirWorkingName + os.sep
   gp.CreateFolder(dirWorkingContainer, dirWorkingName)
   gp.Workspace = gp.ScratchWorkspace = dirWorking

   # Copy feats to intermediate location to avoid messing with the original (respects selection, if any)
   gp.CopyFeatures_management(featsInput, "in_memory/feats")
   gp.MakeFeatureLayer_management("in_memory/feats", feats)
   #gp.FeatureClassToFeatureClass_conversion(gp.Describe(featsInput).CatalogPath, "in_memory", "feats")
   #gp.Copy(gp.Describe(featsInput).CatalogPath, feats)
   featsDesc = gp.Describe(feats)
      
   # Divide cost raster by cell size to get units in cost *per unit distance*, which CostDistance assumes, rather than what we're asking for, which is *total* cost to move through cell). Convert to float first to ensure divide result is a float.
   gp.Float_sa(costInput, cost + "f")
   gp.Divide_sa(cost + "f", gp.Cellsize, cost)
   gp.Delete(cost + "f")
   
   # If user opts for equal weight, add a constant (=1) weight field
   if equalWeight == True:
      weightColumn = "spiweight"
      gp.AddField(feats, weightColumn, "short")
      gp.CalculateField(feats, weightColumn, "1")
   
   #gp.AddMessage("cost: " + cost)
   #gp.AddMessage("maxCostDistance: " + str(maxCostDistance))
   #gp.AddMessage("feats: " + feats)
   #gp.AddMessage("weightColumn: " + weightColumn)
   #gp.AddMessage("equalWeight: " + str(equalWeight))
   gp.AddMessage("dirWorking: " + dirWorking)
   gp.AddMessage("outGrid: " + outGrid)
   #gp.AddMessage("convertToInteger: " + str(convertToInteger))
   #gp.AddMessage("intermediateOutput: " + intermediateOutput)
   
#   raise spie.spiException("TestStop", gp)
   
## LOOP 1: COST DISTANCE ##
# This loop gives us 1) cost distance for each feat; 2) cost distance maximum for all cost distances

   maxCostDistMax = 0 # Track highest cost distance maximum for use as "anchor" in case user doesn't specify maxCostDistance
   featsRows = gp.SearchCursor(feats)
   featRow = featsRows.Next()
   while featRow:
      featID = str(featRow.GetValue(featsDesc.OIDFieldName))
      gp.SetProgressorLabel("Calculating cost distance for feature " + featID)

      # Select this single feature out for doing CostDistance
      gp.SelectLayerByAttribute_management(feats, "NEW_SELECTION", '"' + featsDesc.OIDFieldName + '" = ' + featID)
      
      # Figure cost distance for single feat
      time.sleep(1)
      gp.CostDistance(feats, cost, costDist + featID)

      # Get maximum distance of cost distance raster
      costDistMax = float(gp.GetRasterProperties(costDist + featID, "MAXIMUM").GetOutput(0))

      # If user has set upper limit for cost, set all cells above that limit to it
      if costDistMax > maxCostDistance and maxCostDistance != 0:
         gp.SingleOutputMapAlgebra("con(" + costDist + featID + " > " + str(maxCostDistance) + ", " + str(maxCostDistance) + ", " + costDist + featID + ")", costDist + "temp")
         gp.Delete(costDist + featID)
         gp.Rename(costDist + "temp", costDist + featID)
         costDistMax = float(gp.GetRasterProperties(costDist + featID, "MAXIMUM").GetOutput(0))

      if costDistMax > maxCostDistMax: maxCostDistMax = costDistMax

      gp.SetProgressorPosition() # Finished with this feat
      featRow = featsRows.Next()

   del featRow
   del featsRows
   gp.SelectLayerByAttribute_management(feats, "CLEAR_SELECTION")
   
   gp.AddMessage('maxCostDistMax: ' + str(maxCostDistMax))
      
## LOOP 2: INFLUENCE ##
# This loop normalizes each cost distance over maximum of cost distance maximums, calculates influence, and multiplies by weight

   featsRows = gp.SearchCursor(feats)
   featRow = featsRows.Next()
   while featRow:
      featID = str(featRow.GetValue(featsDesc.OIDFieldName))
      gp.SetProgressorLabel("Calculating influence for feature " + featID)

      # Normalize cost distance over maximum of cost distance maximums
      # Linear normalization function as before: (x - min) / (max - min) but here we rely on min = 0 (smallest cost distance is always 0)
      # This means 0-1 for feature with largest range; 0-.xxx for all others (so normalization scale is the same everywhere)
      # Have to do this before inverting to "influence" to preserve max influence = 1 at feature cell (i.e., where cost distance = 0)
      gp.Divide_sa(costDist + featID, maxCostDistMax, costDist + featID + 'norm')
 
      # Invert cost distance to influence and multiply by weight to get units in weight (e.g., people)
      normStr = "(1 - " + costDist + featID + 'norm' + ") * " + str(featRow.GetValue(weightColumn))
      gp.SingleOutputMapAlgebra(normStr, influence + featID)
      
      gp.Delete(costDist + featID)
      gp.Delete(costDist + featID + 'norm')

      gp.SetProgressorPosition() # Finished with this feat
      gp.AddMessage("Finished with feature " + featID + " with max influence " + str(gp.GetRasterProperties(influence + featID, "MAXIMUM").GetOutput(0)))
      featRow = featsRows.Next()
      
   del featRow
   del featsRows
   
## WRAP UP ##

   gp.SetProgressorPosition(featsCount * 2) # Finished with all feats
   gp.SetProgressorLabel("Finalizing...")
   
   # Add all influence grids
   util.addRastersFromIDs(gp, influence, feats, "totInf")
   
   # Optionally convert final result to integer (round by adding 0.5)
   if convertToInteger == True:
      gp.SingleOutputMapAlgebra("int(totInf + 0.5)", "totInfInt")
      gp.Delete("totInf")
      gp.Rename("totInfInt", "totInf")
      
   # Copy out final result
   gp.CopyRaster_management("totInf", outGrid)
   gp.CalculateStatistics_management(outGrid)
   gp.Delete("totInf")
   
   # Handle intermediate grids
   if intermediateOutput == "Zip":
      zipFileName = util.overwriteSafeName(os.path.dirname(outGrid), dirWorkingName + ".zip")
      gp.AddMessage("Zipping " + dirWorking)
      import zipfile
      zipf = zipfile.ZipFile(os.path.join(os.path.dirname(outGrid), zipFileName), "w", compression = zipfile.ZIP_DEFLATED)
      util.recursive_zip(zipf, dirWorking)
      zipf.close()
      gp.AddMessage("Deleting " + dirWorking)
      gp.Delete(dirWorking)
   elif intermediateOutput == "Delete":
      gp.AddMessage("Deleting " + dirWorking)
      while os.path.isdir(dirWorking): gp.Delete(dirWorking)

   gp.SetProgressorPosition(featsCount + 1)
   gp.CheckInExtension("Spatial")

finally:
   gp.GetMessages()
