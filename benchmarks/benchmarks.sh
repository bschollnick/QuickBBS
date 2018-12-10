#
#   -l turns on variable length, since this is a dynamically produced output
#       http://stackoverflow.com/questions/579450/load-testing-with-ab-fake-failed-requests-length
#
#   -w suppresses the distribution chart
#

clear
echo "The test files are expected to be in http://127.0.0.1:8888/albums/verification_suite/benchtests"
echo "Please ensure these files exist"
echo ""
read -p "Press [Enter] key to start benchmarking or Ctrl-C to abort..."

echo "Running 1 MB test file benchmarks"
echo "---------------------------------------------------------------------------------------" >> $1.txt
#ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test1.bin?download" >> $1.txt
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/download/fcf650d1-f8f0-4cc9-977e-075059821117/" >> $1.txt

echo "---------------------------------------------------------------------------------------" >> $1.txt
sleep 5
echo "Running 2 MB test file benchmarks"
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test2.bin?download" >> $1.txt
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/download/057239fc-c33f-4c6b-b758-59801e578be1/" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt
sleep 5
echo "Running 5 MB test file benchmarks"
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test5.bin?download" >> $1.txt
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/download/33871d58-2bf8-4cd5-aa0a-4e4c3f692a4d/" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt
sleep 5
echo "Running 10 MB test file benchmarks"
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test10.bin?download" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt
sleep 5
echo "Running 30 MB test file benchmarks"
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test30.bin?download" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt
sleep 5
echo "Running 50 MB test file benchmarks"
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test50.bin?download" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt
sleep 5
echo "Running 100 MB test file benchmarks"
ab -n 200 -c 50 -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test100.bin?download" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt


echo "Running load testing"
echo "---------------------------------------------------------------------------------------" >> $1_perf.txt
#httperf --server 127.0.0.1 --port 8888 --num-conns 200 --rate 50 --timeout 1 --uri "/albums/verification_suite/benchtests/test1.bin?download" >> $1_perf.txt
httperf --server 127.0.0.1 --port 8888 --num-conns 200 --rate 50 --timeout 1 --uri "/download/e0bea8f5-f3bc-4a13-ae0b-ab34a8dc2522" >> $1_perf.txt
echo "---------------------------------------------------------------------------------------" >> $1_perf.txt
httperf --server 127.0.0.1 --port 8888 --num-conns 200 --rate 100 --timeout 1 --uri "/albums/verification_suite/benchtests/test2.bin?download" >> $1_perf.txt
echo "---------------------------------------------------------------------------------------" >> $1_perf.txt
httperf --server 127.0.0.1 --port 8888 --num-conns 200 --rate 100 --timeout 1 --uri "/albums/verification_suite/benchtests/test5.bin?download" >> $1_perf.txt
echo "---------------------------------------------------------------------------------------" >> $1_perf.txt

