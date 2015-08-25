.. Gallery documentation master file, created by
   sphinx-quickstart on Sun Feb 15 15:25:48 2015.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Benchmarks
===================================

The Gallery package, is quite fast, but optimization is always an option.

Several factors come into play:

1) The Twistd framework is quite efficient and delivers quite a punch.


Index Page Benchmarks
========================

This was started in August 2015, so I do not have historical comparisons, but moving forward
this can help guide the development of the gallery index page(s).  The verification suite has
decent number of different graphics / file formats, and thus can be affected by the performance
of the plugin architecture.

ab -n 200 -c 50  -d -l http://127.0.0.1:8888/albums/verification_suite

==========  ============  ==========  ======  ==========  ==========  ==========
   Date     System            OS       Ram    Twistd Ver  Head          RPS
==========  ============  ==========  ======  ==========  ==========  ==========
08/25/2015  2.9 i5 iMac   10.10.4      8 Gb   15.3.0      afad0f1     97.98 #/s
08/25/2015  3.4 i5 iMac   10.11.0 B6   8 Gb   15.3.0      afad0f1     118.55 #/s
==========  ============  ==========  ======  ==========  ==========  ==========


File Transfer Benchmarks
========================

Measured in Requests per Second - Tested using ApacheBench v2.3 (Rev 1663405)

Generated using the following Settings:

* Concurrency Level @ 50
* Using the base command line of ab -n 200 -c 50  -d -l

The files are filled with Random Data, and randomly created, with a final file size of:

  * 1 MB
  * 2 MB
  * 5 MB
  * 10 MB
  * 30 MB
  * 50 MB
  * 100 MB

To create the test verification files, use the create_test_files.py.
The code to create the random data file is from http://stackoverflow.com/questions/14275975/creating-random-binary-files

==========  ============  ==========  ======  ==========  ==========  ==========  ==========  ==========  ==========  ==========  ==========  ==========
   Date     System            OS       Ram    Twistd Ver  Head         1 MB        2 MB        5 MB         10 MB      30 MB        50 MB      100 MB
==========  ============  ==========  ======  ==========  ==========  ==========  ==========  ==========  ==========  ==========  ==========  ==========
04/15/2015                                    15.0.0                  238.62 #/s  123.47 #/s  52.18 #/s   29.10 #/s   14.30 #/s   11.03 #/s   5.70 #/s
06/08/2015                                    15.2.1                  246.26 #/s  149.39 #/s  70.23 #/s   38.87 #/s   14.29 #/s   8.39 #/s    4.29 #/s
07/31/2015                                    15.2.1                  294.96 #/s  175.96 #/s  60.26 #/s   32.34 #/s   13.71 #/s   8.23 #/s    4.61 #/s
08/25/2015  3.4 i5 iMac   10.11.0 B6   8 Gb   15.2.1      afad0f1     256.24 #/s  146.01 #/s   78.45 #/s  46.30 #/s   15.95 #/s   9.81 #/s    4.80 #/s
08/25/2015  3.4 i5 iMac   10.11.0 B6   8 Gb   15.3.0      afad0f1     353.87 #/s  208.66 #/s   94.17 #/s  46.42 #/s   16.33 #/s   10.08 #/s    5.11 #/s
08/25/2015  2.9 i5 iMac   10.10.4      8 Gb   15.3.0      afad0f1     296.67 #/s  178.49 #/s   79.75 #/s  42.09 #/s   14.42 #/s   8.81 #/s    4.42 #/s
==========  ============  ==========  ======  ==========  ==========  ==========  ==========  ==========  ==========  ==========  ==========  ==========



.. toctree::
   :titlesonly:
   :maxdepth: 2
