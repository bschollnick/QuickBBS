import os
import os.path
import time
from stat import ST_MODE, ST_INO, ST_DEV, \
    ST_NLINK, ST_UID, ST_GID, \
    ST_SIZE, ST_ATIME, ST_MTIME, \
    ST_CTIME


class	UnifiedDirectory:
		"""
		An Attempt to unify directories, and archives into one single storage package.

		For example:

		 		gallery_listings = unified.Unified_Directory ()
				gallery_listings.populate_file_data_from_filesystem 
				( filepathname = directory_path)
				print "files: ",gallery_listings.files,"/n/n"
				print "subdirectories: ",gallery_listings.subdirectories, "/n/n"
 				print "Display Gallery for ", gallery_listings.root_path
		"""
		def		__init__ ( self ):
			self.rar_file_types 	= ['cbr', 'rar']
			self.zip_file_types		= ['cbz', 'zip']
			self.archive_file_types = self.rar_file_types + self.zip_file_types
			
			self.files_to_ignore 	= [ '.ds_store',]		# 	File filter to ignore
			
			self.root_path 			= None		#	This is the path in the OS that is being examined (e.g. /Volumes/Users/username/ )
			self.subdirectories 	= []		#	This is the subdirectories that exist in that path (e.g. Desktop, Music, Videos, etc)
	
			
			self.files				= []		#	This is the list of files that are in the root_path.
												#	Each file consists of a dictionary containing:
												#
												#		* Filename
												#		* st_mode	- Unix chmod
												#		* st_ino	- inode number
												#		* st_dev	- Unix Device
												#		* st_nlink	- hard link count
												#		* st_uid	- User/Owner ID
												#		* st_gid	- Group ID of Owner
												#		* st_size	- File size
												#		* st_atime	- Last Access time
												#		* st_mtime	- Last Modified Time
												#		* st_ctime	- Last Metadata change
												#		* dot_extension 	- File extension with . prefix (lower case)
												#		* file_extension	- File Extension without . prefix (lower case)
			
		def	_get_directory_list ( self, directory_to_list ):
			"""
				Returns the directories, and files in separate lists.
				
				Low Level function, intended to be used by the populate function.
			"""
			directories = []
			files		= []
			for fileobject in os.listdir ( directory_to_list ):
				if fileobject.lower() in self.files_to_ignore:
					pass
				elif os.path.isdir ( os.sep.join ( [directory_to_list, fileobject] ) ):
					directories.append ( fileobject )
				else:
					files.append ( fileobject )
			return (directories, files)

		def	_return_directories_count ( self ):
			"""
				Return the number of directories that are in the root path
			"""
			return len(self.subdirectories)
			
		def	_return_files_count ( self ):
			"""
				Return the number of files that are in the root path
			"""
			return len(self.files)

		def		is_file_archive ( self, filepathname = None):
			"""
				Is the file that is being passed in, a file in the self.archive_types. 
				
			"""
			if filepathname == None:
				return None
			else:
				extension = os.path.splitext ( filepathname )[1][1:]
				if extension.lower() in self.archive_file_types:
					return True
				else:
					return False

		def		is_rar_file_archive ( self, filepathname = None):
			"""
				Is the file that is being passed in, a file in the self.rar_file_types list. 
				
			"""
			if filepathname == None:
				return None
			else:
				extension = os.path.splitext ( filepathname )[1][1:]
				if extension.lower() in self.rar_file_types:
					return True
				else:
					return False

		def		is_zip_file_archive ( self, filepathname = None):
			"""
				Is the file that is being passed in, a file in the self.zip_file_types list. 
			"""
			if filepathname == None:
				return None
			else:
				extension = os.path.splitext ( filepathname )[1][1:]
				if extension.lower() in self.zip_file_types:
					return True
				else:
					return False


		def natural_sort(self, l): 
			#
			#	http://stackoverflow.com/questions/4836710/does-python-have-a-built-in-function-for-string-natural-sort
			#
			import re
			convert = lambda text: int(text) if text.isdigit() else text.lower() 
			alphanum_key = lambda key: [ convert(c) for c in re.split('([0-9]+)', key) ] 
			return sorted(l, key = alphanum_key)
			
		def		return_file_index ( self, filename ):
			"""
				If the filename exists in the index, then return the 0 based index of the file.
				
				Else, return -1 on error.
			"""
			try:
				return self.files_index.index ( filename )
			except:
				return -1
				
		def		populate_file_data_from_filesystem ( self, filepathname = None, sorted=False, expand_archives = False):
			"""
			Populates this node.
				
			Updates the self.files and self.subdirectories dictionaries in the class.

			sorted - if true, will naturally sort the filenames, and subdirectory names, 
						ensuring that they are in a english friendly sorting. 							
						
			expand_archives - If true, will return the listing of the zip or rar archive type.
			
			"""
#			print "---",filepathname
				
			filedata = {}				#	Clear out old filedata

			#		Set the root path, based off the filepathname information
			
			if filepathname == None:
				#
				#	Invalid request for data.  Return Empty data.
				#
				#print "Returned due to None"
				return False

			self.root_path = os.path.split ( filepathname )[0]
			if os.path.isdir ( filepathname ):
				#
				#	Is directory, return all data on the files within
				#
				self.subdirectories = []	# 	Since we are now invoking, to re-populate, clear out all subdirectory information
				self.subdirectory_index = []
				self.files = []				# 	Since we are now invoking, to re-populate, clear out all file information
				self.files_index = []
				
				raw_directories, raw_files = self._get_directory_list ( directory_to_list = filepathname )

				for directoryname in raw_directories:
					directorydata = {}
					st = os.stat ( os.sep.join ([filepathname, directoryname]) )
#					print "is directory"
#					print st
					dir_subdirectories, dir_files = self._get_directory_list ( os.sep.join ([filepathname, directoryname]) )
					
					directorydata [ "directoryname"]    = directoryname
					directorydata [ "parentdirectory" ] = os.path.split (filepathname)
					directorydata [ "st_mode" ] 	= st[ST_MODE]
					directorydata [ "st_inode" ] = st[ST_INO]
					directorydata [ "st_dev" ] 	= st[ST_DEV]
					directorydata [ "st_nlink" ] = st[ST_NLINK]
					directorydata [ "st_uid" ] 	= st[ST_UID]
					directorydata [ "st_gid" ] 	= st[ST_GID]
					directorydata [ "compressed" ] 	= st[ST_SIZE]
					directorydata [ "st_size" ] 	= 0#os.path.getsize ( filepathname )#st[ST_SIZE]
					directorydata [ "st_atime" ] = st[ST_ATIME]
					directorydata [ "raw_st_mtime" ] = st[ST_MTIME]
					directorydata [ "st_mtime" ] = time.asctime(time.localtime(st[ST_MTIME])) #st[ST_MTIME]
					directorydata [ "st_ctime" ] = st[ST_CTIME]
					directorydata [ "dot_extension" ] = ".dir"
					directorydata [ "file_extension" ] = "dir"
					directorydata [ "number_files" ] = len(dir_files)
					directorydata [ "number_dirs" ] = len(dir_subdirectories)
		
					self.subdirectories.append ( directorydata)
					self.subdirectory_index.append ( directoryname )

				for x in raw_files:
					#
					#	Take each file in the directory, and add it to the files listing
					#
					self.populate_file_data_from_filesystem ( filepathname = filepathname + os.sep + x )
					self.files_index.append ( x )
					
				return

			if os.path.isfile ( filepathname ):
				if self.is_file_archive ( filepathname ) and expand_archives == True:
#					print "archive"
					if 	self.is_rar_file_archive ( filepathname ):
#						print "processing rar"
						rar_filepathname = filepathname
						import rarfile
						archivefile = rarfile.RarFile ( rar_filepathname, 'r')
#						print "processing zip"
					elif self.is_zip_file_archive ( filepathname ):
						zip_filepathname = filepathname
						import zipfile
						archivefile = zipfile.ZipFile ( zip_filepathname, 'r')
#						print "processing zip"

					infolist = archivefile.infolist ()
					for info in infolist:
						filedata = {}
						filedata [ "filename" ] = info.filename
						filedata [ "archivefilename" ] = filepathname
						filedata [ "st_mode" ] 	= None
						filedata [ "st_inode" ] = None
						filedata [ "st_dev" ] 	= None
						filedata [ "st_nlink" ] = None
						filedata [ "st_uid" ] 	= None
						filedata [ "st_gid" ] 	= None
						filedata [ "st_size" ] 	= info.file_size
						filedata [ "compressed" ] 	= info.compress_size
						filedata [ "st_atime" ] = None
						filedata [ "raw_st_mtime" ] = st[ST_MTIME]
						filedata [ "st_mtime" ] = time.asctime(time.localtime(st[ST_MTIME])) #st[ST_MTIME]
						filedata [ "st_ctime" ] = st[ST_CTIME]
						filedata [ "st_ctime" ] = None
						filedata [ "dot_extension" ] = os.path.splitext ( info.filename )[1].lower()
						filedata [ "file_extension" ] = os.path.splitext ( info.filename )[1][1:].lower()
						self.files.append ( filedata )
				else:
#					print "not archive"
					st = os.stat ( filepathname )
					filedata [ "filename" ] = os.path.split (filepathname)[1]
					filedata [ "fq_filename" ] = filepathname
					filedata [ "st_mode" ] 	= st[ST_MODE]
					filedata [ "st_inode" ] = st[ST_INO]
					filedata [ "st_dev" ] 	= st[ST_DEV]
					filedata [ "st_nlink" ] = st[ST_NLINK]
					filedata [ "st_uid" ] 	= st[ST_UID]
					filedata [ "st_gid" ] 	= st[ST_GID]
					filedata [ "compressed" ] 	= st[ST_SIZE]
					filedata [ "st_size" ] 	= st[ST_SIZE]
					filedata [ "st_atime" ] = st[ST_ATIME]
					filedata [ "raw_st_mtime" ] = st[ST_MTIME]
					filedata [ "st_mtime" ] = time.asctime(time.localtime(st[ST_MTIME])) #st[ST_MTIME]
					filedata [ "st_ctime" ] = st[ST_CTIME]
					filedata [ "dot_extension" ] = os.path.splitext ( filepathname )[1].lower()
					filedata [ "file_extension" ] = os.path.splitext ( filepathname )[1][1:].lower()
					self.files.append ( filedata )

				if sorted:
					self.natural_sort ( self.files_index )
					self.natural_sort ( self.subdirectory_index )
				
			return True