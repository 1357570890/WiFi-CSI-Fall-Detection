import torch
from torch.utils.data import DataLoader
import sys
import os
from sklearn.metrics import confusion_matrix

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "05_windows_server"))
from core.ai_engine import TwoStreamFallDetector
from train_cnn import CSIDataset

def evaluate():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = TwoStreamFallDetector(rx_num=1).to(device)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(script_dir, "..", "04_models", "model_cnn_1rx.pth")
    model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
    model.eval()

    dataset_path = os.path.join(script_dir, "dataset")
    test_dataset = CSIDataset(dataset_path, rx_num=1, mode='test')
    test_loader = DataLoader(test_dataset, batch_size=64, shuffle=False)

    all_preds = []
    all_labels = []

    with torch.no_grad():
        for seqs, feats, labels in test_loader:
            seqs = seqs.to(device)
            feats = feats.to(device)
            outputs = model(seqs, feats)
            _, predicted = torch.max(outputs.data, 1)
            all_preds.extend(predicted.cpu().numpy())
            all_labels.extend(labels.numpy())

    cm = confusion_matrix(all_labels, all_preds)
    print("Confusion Matrix:")
    print(cm)
    
    # Calculate per-class accuracy
    classes = [0, 1, 2, 3]
    for i in range(cm.shape[0]):
        total = sum(cm[i, :])
        correct = cm[i, i]
        print(f"Class {i} Accuracy: {correct}/{total} = {correct/total*100:.2f}%")

if __name__ == "__main__":
    evaluate()
