
## EXCEPTIONS ##

import sys

class spiException(Exception):
   
   def __init__(self, errorType, gp, args = []):
      
      if errorType == "LicenseError":
         gp.AddError("Spatial Analyst license is unavailable.")
      
      elif errorType == "WeightError":
         gp.AddError("A weight attribute was specified, but at least one influence feature is missing.")
         sys.exit() # Causes tool to rerun, with parameters populated as before
      
      elif errorType == "ProjectionError":
         gp.AddError(str(args) + " is not in a projected coordinate system, which is required for this tool. Please project your data so that it has a linear unit.")
         sys.exit()

      elif errorType == "PointRangeError":
         gp.AddError("Invalid number of influence features: you need more than 0, and really don't want to run with more than 1000.")
         sys.exit()
      
      elif errorType == "CostSizeError":
         gp.AddError("Cost surface grid has more than 100,000,000 cells (~ 10000 x 10000). Reduce cell size to achieve fewer cells.")
         sys.exit()
      
      elif errorType == "DiskSpaceError":
         gp.AddError("Not enough disk space to run tool. Space required: " + str(args[0]) + " Space available: " + str(args[1]))
         sys.exit()
      
      elif errorType == "CostRangeError":
         gp.AddError("Cost surface grid cannot have values less than or equal to 0, or greater than 10000. Rescale costs if necessary.")
         sys.exit()
         
      elif errorType == "OIDError":
         gp.AddError("A unique object ID is required for the influence feature class.")
         sys.exit()
         
      elif errorType == "WeightRangeError":
         gp.AddError("Mean weight for influence features is greater than 100000. Rescale to a narrower range.")
         sys.exit()
      
      elif errorType == "OutputPathError":
         gp.AddError("Output grid path contains spaces. Please choose a path without spaces.")
         sys.exit()
      
      elif errorType == "NoDataFeatsError":
         gp.AddError("At least one influence feature is located in a cost surface cell with NoData. Adjust cost surface or remove influence features not on surface. OIDs: " + args[0])
         sys.exit()
      
      elif errorType == "OutputNameLengthError":
         gp.AddError("Output grid name cannot have more than 13 characters.")
         sys.exit()

      elif errorType == "OutputNameBadCharsError":
         gp.AddError("Output raster name contains special characters: " + str(args))
         sys.exit()
      
      elif errorType == "TooManyRastersError":
         gp.AddError("addRastersFromIDs: you're trying to add more than 2500 rasters based on your number of influence features; for now this is disallowed.")
         sys.exit()

      elif errorType == "TestStop":
         gp.AddWarning("Stopped prematurely for testing.")
         sys.exit()

      else:
         gp.AddError("General spiException")
         sys.exit()
