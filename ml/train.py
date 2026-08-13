import os
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score, accuracy_score
import joblib
from scipy.signal import butter, filtfilt

# --- Configuration ---
DATA_DIR = "./SisFall_dataset"  # Path to downloaded SisFall dataset
MODEL_OUTPUT = "fall_detection_model.joblib"
WINDOW_SIZE = 200 * 3  # 3 seconds @ 200Hz
OVERLAP = 0.5
CUTOFF_FREQ = 5.0
FS = 200.0

# --- Preprocessing ---
def low_pass_filter(data, cutoff, fs, order=4):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    y = filtfilt(b, a, data)
    return y

def extract_features(window_acc):
    """
    Extracts statistical features from a window of acceleration data (Nx3 array).
    """
    # Calculate magnitude
    magnitude = np.sqrt(np.sum(window_acc**2, axis=1))
    
    # Low-pass filter the magnitude
    mag_filtered = low_pass_filter(magnitude, CUTOFF_FREQ, FS)
    
    # Feature extraction
    mean = np.mean(mag_filtered)
    std = np.std(mag_filtered)
    min_acc = np.min(mag_filtered)  # Captures free-fall dip
    max_acc = np.max(mag_filtered)  # Captures impact peak
    range_acc = max_acc - min_acc
    
    # SMA (Signal Magnitude Area)
    sma = np.sum(mag_filtered) / len(mag_filtered)
    
    # Peak Jerk (derivative of acceleration)
    jerk = np.diff(mag_filtered)
    peak_jerk = np.max(np.abs(jerk)) if len(jerk) > 0 else 0
    
    return [mean, std, min_acc, max_acc, range_acc, sma, peak_jerk]

# --- Data Loading (With Fallback) ---
def load_data():
    """
    Loads the SisFall dataset. If not found, generates a synthetic dataset
    for demonstration and pipeline testing purposes.
    """
    if os.path.exists(DATA_DIR):
        print(f"Loading actual dataset from {DATA_DIR}...")
        # Add actual SisFall parsing logic here
        pass
        
    print(f"Dataset not found at {DATA_DIR}. Generating synthetic mock data for pipeline testing...")
    X, y, groups = [], [], []
    
    # Simulate 38 subjects (like SisFall)
    for subject_id in range(1, 39):
        # 15 Falls, 19 ADLs per subject
        for fall_id in range(15):
            # Synthetic Fall: Contains a dip (<0.4g) and a spike (>2.2g)
            window = np.ones((WINDOW_SIZE, 3)) * (1.0 / np.sqrt(3)) # Base 1g magnitude
            # Add free fall dip
            window[200:250] = 0.1 
            # Add impact spike
            window[250:300] = 3.0 
            
            features = extract_features(window)
            X.append(features)
            y.append(1) # 1 = Fall
            groups.append(subject_id)
            
        for adl_id in range(19):
            # Synthetic ADL: Normal movement (Walking, sitting, etc.)
            window = np.ones((WINDOW_SIZE, 3)) * (1.0 / np.sqrt(3))
            # Add some random noise
            window += np.random.normal(0, 0.2, (WINDOW_SIZE, 3))
            
            features = extract_features(window)
            X.append(features)
            y.append(0) # 0 = ADL (Not a fall)
            groups.append(subject_id)
            
    return np.array(X), np.array(y), np.array(groups)

# --- Training and Evaluation ---
def train_and_evaluate():
    print("Loading data...")
    X, y, groups = load_data()
    print(f"Loaded {len(X)} windows. Features shape: {X.shape}")
    
    # Leave-One-Subject-Out Cross Validation
    logo = LeaveOneGroupOut()
    
    print("\nTraining Random Forest with Leave-One-Subject-Out CV...")
    
    # Store predictions for overall metrics
    all_y_true = []
    all_y_pred = []
    
    model = RandomForestClassifier(n_estimators=100, random_state=42, class_weight='balanced')
    # Uncomment to test SVM: 
    # model = SVC(kernel='rbf', probability=True, class_weight='balanced')
    
    fold = 1
    for train_idx, test_idx in logo.split(X, y, groups):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        
        all_y_true.extend(y_test)
        all_y_pred.extend(preds)
        fold += 1
        
    print("\n--- Cross-Validation Results ---")
    print(confusion_matrix(all_y_true, all_y_pred))
    print(classification_report(all_y_true, all_y_pred, target_names=["ADL", "Fall"]))
    
    # Final model trained on ALL data for deployment
    print("Training final model on full dataset for deployment...")
    final_model = RandomForestClassifier(n_estimators=100, random_state=42, class_weight='balanced')
    final_model.fit(X, y)
    
    joblib.dump(final_model, MODEL_OUTPUT)
    print(f"Model saved to {MODEL_OUTPUT}")

if __name__ == "__main__":
    train_and_evaluate()
