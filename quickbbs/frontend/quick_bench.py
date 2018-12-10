import time
import requests
import statistics

number_of_repeats = 100

urls_to_check = ["http://nerv.local:8888/albums/",
                 "http://nerv.local:8888/albums/hentai idea/",
                 "http://nerv.local:8888/albums/Hentai%20Idea?page=2",
                 "http://nerv.local:8888/albums/Hentai%20Idea?page=10",
                 "http://nerv.local:8888/albums/Hentai%20Idea?page=20",
                 "http://nerv.local:8888/albums/Hentai%20Idea?page=30",
                 "http://nerv.local:8888/albums/Hentai%20Idea?page=40",
                 "http://nerv.local:8888/albums/Hentai%20Idea?page=50"]

print ("Priming")
print ()
for url in urls_to_check:
    times = []
    requests.get(url).elapsed.total_seconds()

print("Waiting for 30 seconds")
time.sleep(30)
print ("Main test @ %s # of repeats" % number_of_repeats)
start = time.time()
for url in urls_to_check:
    times = []
    for inc in range(1, number_of_repeats):
        elapsed = requests.get(url).elapsed.total_seconds()
        times.append(elapsed)
    print ("---------------")
    print (url)
    print ("Min : %.4f" % min(times))
    print ("Max : %.4f" % max(times))
    print ("Average : %.4f" % (sum(times) / float(len(times))))
    print ("St Dev: %.4f" % statistics.stdev(times))

print("Total Elapsed Test Time: %.4f" %  (time.time()-start))
