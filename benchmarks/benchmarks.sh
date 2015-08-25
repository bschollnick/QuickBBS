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

echo "Running Verification Suite Index Benchmarks"
echo "---------------------------------------------------------------------------------------" >> $1.txt
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt

echo "Running 1 MB test file benchmarks"
echo "---------------------------------------------------------------------------------------" >> $1.txt
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test1.bin" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt
sleep 5
echo "Running 2 MB test file benchmarks"
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test2.bin" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt
sleep 5
echo "Running 5 MB test file benchmarks"
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test5.bin" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt
sleep 5
echo "Running 10 MB test file benchmarks"
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test10.bin" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt
sleep 5
echo "Running 30 MB test file benchmarks"
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test30.bin" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt
sleep 5
echo "Running 50 MB test file benchmarks"
ab -n 200 -c 50  -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test50.bin" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt
sleep 5
echo "Running 100 MB test file benchmarks"
ab -n 200 -c 50 -d -l "http://127.0.0.1:8888/albums/verification_suite/benchtests/test100.bin" >> $1.txt
echo "---------------------------------------------------------------------------------------" >> $1.txt


echo "Running load testing"
echo "---------------------------------------------------------------------------------------" >> $1_perf.txt
httperf --server 127.0.0.1 --port 8888 --num-conns 200 --rate 50 --timeout 1 --uri "/albums/verification_suite/benchtests/test1.bin" >> $1_perf.txt
echo "---------------------------------------------------------------------------------------" >> $1_perf.txt
httperf --server 127.0.0.1 --port 8888 --num-conns 200 --rate 100 --timeout 1 --uri "/albums/verification_suite/benchtests/test1.bin" >> $1_perf.txt
echo "---------------------------------------------------------------------------------------" >> $1_perf.txt
httperf --server 127.0.0.1 --port 8888 --num-conns 200 --rate 125 --timeout 1 --uri "/albums/verification_suite/benchtests/test1.bin" >> $1_perf.txt
echo "---------------------------------------------------------------------------------------" >> $1_perf.txt

