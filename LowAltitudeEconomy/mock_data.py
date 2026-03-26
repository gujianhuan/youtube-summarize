import pandas as pd
import numpy as np
import random

# Define regions and their approximate coordinates (Lat, Lon)
regions = {
    "北京": [39.9042, 116.4074],
    "上海": [31.2304, 121.4737],
    "广东": [23.1291, 113.2644],
    "深圳": [22.5431, 114.0579], # Treat Shenzhen separately as it's a hub
    "四川": [30.5728, 104.0668],
    "浙江": [30.2741, 120.1551],
    "江苏": [32.0603, 118.7969],
    "湖南": [28.2282, 112.9388],
    "安徽": [31.8601, 117.2849],
    "陕西": [34.3416, 108.9398]
}

def generate_data():
    data = []
    
    for region, coords in regions.items():
        # Simulate realistic data with some variance
        # Tech hubs (Beijing, Shanghai, Shenzhen) get higher stats
        multiplier = 1.0
        if region in ["北京", "上海", "深圳"]:
            multiplier = 2.5
        elif region in ["广东", "江苏", "浙江"]:
            multiplier = 1.8
            
        flight_hours = int(np.random.normal(50000, 10000) * multiplier)
        investment = round(np.random.normal(20, 5) * multiplier, 2) # Billion RMB
        tenders = int(np.random.normal(50, 10) * multiplier)
        enterprises = int(np.random.normal(200, 50) * multiplier)
        patents = int(np.random.normal(100, 20) * multiplier)
        drones = int(np.random.normal(10000, 2000) * multiplier)
        pilots = int(np.random.normal(500, 100) * multiplier)
        accidents = int(np.random.poisson(2) * (multiplier * 0.5)) # Fewer accidents
        
        # New fields for detailed analysis
        vertiports = int(np.random.normal(15, 5) * multiplier) # Vertical takeoff/landing points
        
        # Scenarios (Percentage or raw counts)
        scenario_logistics = int(flight_hours * 0.4 * np.random.uniform(0.8, 1.2))
        scenario_tourism = int(flight_hours * 0.2 * np.random.uniform(0.8, 1.2))
        scenario_agri = int(flight_hours * 0.15 * np.random.uniform(0.8, 1.2))
        scenario_inspection = int(flight_hours * 0.25 * np.random.uniform(0.8, 1.2))
        
        data.append({
            "Region": region,
            "Lat": coords[0],
            "Lon": coords[1],
            "FlightHours": flight_hours,
            "Investment_Billion": investment,
            "Tenders": tenders,
            "Enterprises": enterprises,
            "Patents": patents,
            "Drones": drones,
            "Pilots": pilots,
            "Accidents": accidents,
            "Vertiports": vertiports,
            "Scenario_Logistics": scenario_logistics,
            "Scenario_Tourism": scenario_tourism,
            "Scenario_Agri": scenario_agri,
            "Scenario_Inspection": scenario_inspection
        })
        
    df = pd.DataFrame(data)
    return df

if __name__ == "__main__":
    df = generate_data()
    df.to_csv("low_altitude_data.csv", index=False)
    print("Mock data generated: low_altitude_data.csv")
