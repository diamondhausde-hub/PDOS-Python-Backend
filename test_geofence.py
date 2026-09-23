from routers.deps import haversine_distance

def test_haversine_distance():
    # Example 1: Known distance
    # Paris: 48.8566, 2.3522
    # London: 51.5074, -0.1278
    # Distance is approx 344 km = 344000 meters
    dist = haversine_distance(48.8566, 2.3522, 51.5074, -0.1278)
    assert 340000 < dist < 350000, f"Distance was {dist}"

    # Example 2: Short distance
    # Two points 300m apart
    lat1, lon1 = 24.7136, 46.6753
    # Approx 1 degree latitude = 111km. 300m = 0.0027 degrees
    lat2, lon2 = lat1 + 0.0027, lon1
    dist_short = haversine_distance(lat1, lon1, lat2, lon2)
    assert 290 < dist_short < 310, f"Short distance was {dist_short}"

    print("Haversine Distance Tests Passed!")

if __name__ == "__main__":
    test_haversine_distance()
