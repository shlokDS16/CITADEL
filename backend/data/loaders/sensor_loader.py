"""
Sensor Data Loader
Loads:
1. UCI Air Quality Dataset (Environmental Sensors)
2. NAB (Numenta Anomaly Benchmark) (Infrastructure metrics)

This data mimics IoT sensor streams for Anomaly Detection.
"""
import pandas as pd
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Generator
from datetime import datetime

class SensorLoader:
    
    UCI_PATH = r"C:\Users\shlok\.cache\kagglehub\datasets\dakshbhalala\uci-air-quality-dataset\versions\1\AirQualityUCI.csv"
    NAB_PATH = r"C:\Users\shlok\.cache\kagglehub\datasets\boltzmannbrain\nab\versions\1"
    
    def load_air_quality(self, limit: int = 1000) -> List[Dict]:
        """
        Load Air Quality data.
        Returns list of readings {timestamp, co_level, temp, humidity, ...}
        """
        if not os.path.exists(self.UCI_PATH):
            print(f"Warning: UCI Air Quality file not found at {self.UCI_PATH}")
            return []
            
        try:
            # Separator is ; and decimals are commas
            df = pd.read_csv(self.UCI_PATH, sep=';', decimal=',', na_values=-200)
            
            # Clean dataframe
            df = df.dropna(subset=['Date', 'Time'])
            
            readings = []
            for _, row in df.head(limit).iterrows():
                try:
                    ts_str = f"{row['Date']} {row['Time']}"
                    # Format: DD/MM/YYYY HH.MM.SS
                    ts = datetime.strptime(ts_str.replace('.', ':'), "%d/%m/%Y %H:%M:%S")
                    
                    reading = {
                        "timestamp": ts.isoformat(),
                        "source": "air_quality_sensor_1",
                        "metric": "CO(GT)",
                        "value": float(row['CO(GT)']) if pd.notna(row['CO(GT)']) else 0.0,
                        "metadata": {
                            "temp": float(row['T']) if pd.notna(row['T']) else 0.0,
                            "humidity": float(row['RH']) if pd.notna(row['RH']) else 0.0
                        }
                    }
                    readings.append(reading)
                except Exception as e:
                    continue
                    
            return readings
            
        except Exception as e:
            print(f"Error loading Air Quality: {e}")
            return []

    def load_nab_metric(self, category: str = "realAWSCloudwatch", file_filter: str = "ec2_cpu") -> List[Dict]:
        """
        Load NAB metric series.
        Category: realAWSCloudwatch, realTraffic, realKnownCause
        """
        base_path = Path(self.NAB_PATH) / category
        if not base_path.exists():
            print(f"Warning: NAB category {category} not found.")
            return []
            
        series = []
        
        for file in base_path.glob("*.csv"):
            if file_filter and file_filter not in file.name:
                continue
                
            try:
                df = pd.read_csv(file)
                # Ensure proper columns
                if 'timestamp' in df.columns and 'value' in df.columns:
                    for _, row in df.iterrows():
                        series.append({
                            "timestamp": row['timestamp'],
                            "source": f"nab_{category}_{file.stem}",
                            "metric": "value",
                            "value": float(row['value'])
                        })
            except Exception as e:
                print(f"Error reading {file}: {e}")
                
        return series

if __name__ == "__main__":
    loader = SensorLoader()
    aq = loader.load_air_quality(limit=5)
    print(f"Loaded {len(aq)} Air Quality readings")
    if aq: print(aq[0])
    
    nab = loader.load_nab_metric("realAWSCloudwatch")
    print(f"Loaded {len(nab)} NAB readings")
    if nab: print(nab[0])
