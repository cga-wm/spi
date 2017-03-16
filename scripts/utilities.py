
## UTILITY FUNCTIONS ##

import os, spiExceptions as spie, re, platform, ctypes
   
def badChars(text):
   foundchars = []
   badchars = re.compile("\W") # any non-alphanumeric char
   found = badchars.search(os.path.basename(text))
   if found:
      foundchars = badchars.findall(os.path.basename(text))
      foundchars = [str(c) for c in foundchars] # don't deal with unicode for now
      if '.' in foundchars: foundchars.remove('.')
      if '+' in foundchars: foundchars.remove('+')
      if '-' in foundchars: foundchars.remove('-')
   return foundchars

# Return byte multiplier for raster cell value type
def getRasterBytes(costInput, gp):
   costValueType = int(gp.GetRasterProperties(costInput, "VALUETYPE").GetOutput(0))
   #gp.AddMessage("costValueType: " + str(costValueType))
   if costValueType == 3 or costValueType == 4 or costValueType == 11: return 1
   if costValueType == 5 or costValueType == 6 or costValueType == 13: return 2
   if costValueType == 7 or costValueType == 8 or costValueType == 9 or costValueType == 14: return 3
   if costValueType == 10 or costValueType == 12: return 4
   return -1

# Return free space (in bytes) of drive containing path
def getFreeSpace(path):
   # get parent dir; doesn't really matter what it is as long as it's a dir
   folder = getParentDir(path)
   if platform.system() == 'Windows':
      free_bytes = ctypes.c_ulonglong(0)
      ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(folder), None, None, ctypes.pointer(free_bytes))
      return free_bytes.value
   else:
      return os.statvfs(folder).f_bfree * os.statvfs(folder).f_bsize

def getParentDir(path):
   if os.path.isdir(path):
      return path
   else:
      path = os.path.abspath(os.path.join(path, '..'))
      return getParentDir(path)

# Get mean of specified field in specified table
def getFieldMean(table, fieldName, rowCount, gp):
   fieldSum = 0
   rows = gp.SearchCursor(table, "", "", fieldName, fieldName + " D")
   row = rows.Next()
   while row:
      rowWeight = row.GetValue(fieldName)
      if rowWeight is None: raise spie.spiException("WeightError", gp)
      fieldSum += row.GetValue(fieldName)
      row = rows.Next()
   gp.AddMessage(fieldName + " mean: " + str(fieldSum / rowCount))
   return fieldSum / rowCount
   del row
   del rows

# Return list of points falling in cost cells with NoData, or polygons with no cost cell overlap
def getNoDataFeatures(raster, features, gp):
   #gp.AddMessage("feature type: " + gp.Describe(features).shapeType)
   noDataPoints = []

   # In 9.3, Arc seems to convert .img to GRID in Sample, so we have to do it manually to avoid column name problem in Sample results
   if os.path.splitext(os.path.basename(raster))[1] != "":
      rastergrid = os.path.dirname(raster) + os.sep + os.path.splitext(os.path.basename(raster))[0][:13]
      gp.CopyRaster_management(raster, rastergrid)
      raster = rastergrid
   
   # if features are points, sample them and make sure resulting values are > 0
   if gp.Describe(features).shapeType == "Point":
      # in_memory causes errors in some (undefined) cases
      gp.Sample(raster, features, os.path.dirname(raster) + os.sep + "pointsSample")
      pointVals = gp.SearchCursor(os.path.dirname(raster) + os.sep + "pointsSample")
      pointVal = pointVals.Next()
      while pointVal:
         #if pointVal.GetValue("RASTERVALU") <= 0: noDataPoints.append(pointVal.GetValue("MASK"))
         if pointVal.GetValue(os.path.splitext(os.path.basename(raster))[0]) <= 0: noDataPoints.append(pointVal.GetValue("MASK"))
         pointVal = pointVals.Next()
      gp.Delete(os.path.dirname(raster) + os.sep + "pointsSample")
   
   # if features are polygons, do polygon to raster (with raster as mask), then iterate through features and make sure >= 1 cell in vat with that id
   elif gp.Describe(features).shapeType == "Polygon":
      fdesc = gp.Describe(features)
      gp.PolygonToRaster_conversion(features, fdesc.OIDFieldName, "pr")
      gp.DeleteRasterAttributeTable_management("pr")
      gp.ExtractByMask("pr", raster, "polyraster")
      gp.Delete("pr")
      gp.MakeRasterLayer_management("polyraster", "polyrasterlyr")
      fcs = gp.SearchCursor(features)
      fc = fcs.Next()
      while fc:
         gp.SelectLayerByAttribute_management("polyrasterlyr", "NEW_SELECTION", ' "Value" = ' + str(fc.GetValue(fdesc.OIDFieldName))) 
         if int(gp.GetCount("polyrasterlyr").GetOutput(0)) == 0: noDataPoints.append(fc.GetValue(fdesc.OIDFieldName))
         fc = fcs.Next()
      del fc, fcs
      gp.Delete("polyraster")
      
   return noDataPoints

# Zip a directory recursively
def recursive_zip(zipf, directory, folder = ""): #gp, 
   directory = str(directory) # not dealing with unicode for now
   for item in os.listdir(directory):
      if os.path.isfile(os.path.join(directory, item)):
         if os.path.splitext(item)[1] != '.lock':
            #gp.AddMessage("Adding " + str(item) + " to " + folder)
            zipf.write(os.path.join(directory, item).encode("ascii"), folder + os.sep + item)
      elif os.path.isdir(os.path.join(directory, item)):
         #gp.AddMessage("Descending into " + str(os.path.join(directory, item)))
         recursive_zip(zipf, os.path.join(directory, item), folder + os.sep + item) #gp, 

# Increment base filename if the file already exists in the specified directory
def overwriteSafeName(directory, filename):
   safeFilename = filename
   if os.path.isfile(os.path.join(directory, filename)) or os.path.isfile(os.path.join(directory, filename + '.zip')) or os.path.isdir(os.path.join(directory, filename)):
      (filenameBase, ext) = os.path.splitext(filename)
      increment = 1
      while os.path.isfile(os.path.join(directory, filenameBase + str(increment) + ext)) or os.path.isfile(os.path.join(directory, filenameBase + str(increment) + ext + '.zip'))  or os.path.isdir(os.path.join(directory, filenameBase + str(increment) + ext)): increment += 1
      safeFilename = filenameBase + str(increment) + ext
   return safeFilename

# Add rasters based on prefix and IDs from feature rows, in batches of 50 to avoid crashes
def addRastersFromIDs(gp, prefix, feats, outputRaster):
   step = 50
   totRows = int(gp.GetCount_management(feats).GetOutput(0))
   batches = totRows / step
   if totRows % step > 0: batches += 1
   if totRows > 2500: raise spie.spiException("TooManyRastersError", gp)
   oid = gp.Describe(feats).OIDFieldName
   
   # Create intermediate rasters, each one a sum of 50 of input rasters
   for batch in range(batches):
      featsRows = gp.SearchCursor(feats)
      featRow = featsRows.Next()
      inputStr = ""
      counter = 0
      batchRow = batch * step

      while featRow:
         if counter >= batchRow and counter < (batchRow + step):
            inputStr += prefix + str(featRow.GetValue(oid)) + "; "
         counter += 1
         featRow = featsRows.Next()
      inputStr = inputStr[:-2]
      #gp.AddMessage("inputStr: " + inputStr)
      gp.WeightedSum(inputStr, outputRaster + "Batch" + str(batch))

      del featRow
      del featsRows
   
   # Add intermediate rasters
   inputStr = ""
   for batch in range(batches): inputStr += outputRaster + "Batch" + str(batch) + "; "
   inputStr = inputStr[:-2]
   #gp.AddMessage("inputStr: " + inputStr)
   gp.WeightedSum(inputStr, outputRaster)

   for batch in range(batches): gp.Delete(outputRaster + "Batch" + str(batch))
