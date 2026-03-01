"""
Red Neuronal para clasificacion de billetes ilegales.
Implementacion desde cero con NumPy - Red feedforward con backpropagation.

Arquitectura: Input(12) -> Dense(128, ReLU) -> Dense(64, ReLU) -> Dense(32, ReLU) -> Dense(1, Sigmoid)
"""

import json
import os
import numpy as np
from models.bcb_database import BCB_ILLEGAL_RANGES, VALID_DENOMINATIONS


class NeuralNetwork:
    def __init__(self, layer_sizes=None):
        if layer_sizes is None:
            layer_sizes = [12, 128, 64, 32, 1]
        self.layer_sizes = layer_sizes
        self.weights = []
        self.biases = []
        self.trained = False
        self.training_history = {"loss": [], "accuracy": []}
        self._initialize_weights()

    def _initialize_weights(self):
        """Inicializacion He para ReLU."""
        np.random.seed(42)
        self.weights = []
        self.biases = []
        for i in range(len(self.layer_sizes) - 1):
            fan_in = self.layer_sizes[i]
            fan_out = self.layer_sizes[i + 1]
            w = np.random.randn(fan_in, fan_out) * np.sqrt(2.0 / fan_in)
            b = np.zeros((1, fan_out))
            self.weights.append(w)
            self.biases.append(b)

    @staticmethod
    def _relu(z):
        return np.maximum(0, z)

    @staticmethod
    def _relu_derivative(z):
        return (z > 0).astype(float)

    @staticmethod
    def _sigmoid(z):
        z = np.clip(z, -500, 500)
        return 1.0 / (1.0 + np.exp(-z))

    def _forward(self, X):
        """Forward pass guardando activaciones para backprop."""
        activations = [X]
        z_values = []
        current = X
        for i in range(len(self.weights) - 1):
            z = current @ self.weights[i] + self.biases[i]
            z_values.append(z)
            current = self._relu(z)
            activations.append(current)
        z = current @ self.weights[-1] + self.biases[-1]
        z_values.append(z)
        output = self._sigmoid(z)
        activations.append(output)
        return activations, z_values

    def predict(self, X):
        """Prediccion: retorna probabilidad de ser ilegal."""
        activations, _ = self._forward(X)
        return activations[-1]

    def _compute_loss(self, y_true, y_pred):
        """Binary cross-entropy loss."""
        eps = 1e-8
        y_pred = np.clip(y_pred, eps, 1 - eps)
        return -np.mean(y_true * np.log(y_pred) + (1 - y_true) * np.log(1 - y_pred))

    def _backpropagate(self, X, y_true, learning_rate):
        """Backpropagation con SGD."""
        m = X.shape[0]
        activations, z_values = self._forward(X)
        y_pred = activations[-1]

        delta = y_pred - y_true
        for i in range(len(self.weights) - 1, -1, -1):
            dw = activations[i].T @ delta / m
            db = np.sum(delta, axis=0, keepdims=True) / m
            if i > 0:
                delta = (delta @ self.weights[i].T) * self._relu_derivative(z_values[i - 1])
            self.weights[i] -= learning_rate * dw
            self.biases[i] -= learning_rate * db

        return self._compute_loss(y_true, y_pred)

    def generate_training_data(self, samples_per_class=5000):
        """Genera datos de entrenamiento sinteticos desde los rangos del BCB."""
        X_list = []
        y_list = []

        for denom in VALID_DENOMINATIONS:
            ranges = BCB_ILLEGAL_RANGES[denom]
            # Muestras ilegales
            for _ in range(samples_per_class // len(VALID_DENOMINATIONS)):
                r = ranges[np.random.randint(len(ranges))]
                serial = np.random.randint(r[0], r[1] + 1)
                X_list.append(self._extract_features(denom, serial))
                y_list.append(1)

            # Muestras legales (fuera de rangos)
            all_min = min(r[0] for r in ranges)
            all_max = max(r[1] for r in ranges)
            generated = 0
            target = samples_per_class // len(VALID_DENOMINATIONS)
            while generated < target:
                serial = np.random.randint(
                    max(1, all_min - 5000000),
                    all_max + 5000000
                )
                is_in_range = any(s <= serial <= e for s, e in ranges)
                if not is_in_range:
                    X_list.append(self._extract_features(denom, serial))
                    y_list.append(0)
                    generated += 1

        X = np.array(X_list, dtype=np.float64)
        y = np.array(y_list, dtype=np.float64).reshape(-1, 1)

        indices = np.random.permutation(len(X))
        return X[indices], y[indices]

    @staticmethod
    def _extract_features(denomination, serial):
        """Extrae features normalizados para la red neuronal."""
        denom_norm = denomination / 50.0
        is_bs10 = 1.0 if denomination == 10 else 0.0
        is_bs20 = 1.0 if denomination == 20 else 0.0
        is_bs50 = 1.0 if denomination == 50 else 0.0
        serial_norm = serial / 150000000.0
        serial_log = np.log10(max(serial, 1)) / 9.0
        last_4 = (serial % 10000) / 10000.0
        mid_4 = ((serial // 10000) % 10000) / 10000.0
        high_4 = ((serial // 100000000) % 10000) / 10000.0
        ends_in_0001 = 1.0 if serial % 10000 == 1 else 0.0
        ends_in_0000 = 1.0 if serial % 10000 == 0 else 0.0
        block_pos = (serial % 450000) / 450000.0
        return [
            denom_norm, is_bs10, is_bs20, is_bs50,
            serial_norm, serial_log,
            last_4, mid_4, high_4,
            ends_in_0001, ends_in_0000, block_pos,
        ]

    def train(self, epochs=100, learning_rate=0.05, batch_size=128, samples=8000):
        """Entrena la red neuronal."""
        self._initialize_weights()
        self.training_history = {"loss": [], "accuracy": []}

        X, y = self.generate_training_data(samples_per_class=samples)

        split = int(0.8 * len(X))
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]

        for epoch in range(epochs):
            indices = np.random.permutation(len(X_train))
            X_shuffled = X_train[indices]
            y_shuffled = y_train[indices]

            epoch_loss = 0
            n_batches = 0
            for start in range(0, len(X_train), batch_size):
                end = min(start + batch_size, len(X_train))
                X_batch = X_shuffled[start:end]
                y_batch = y_shuffled[start:end]
                loss = self._backpropagate(X_batch, y_batch, learning_rate)
                epoch_loss += loss
                n_batches += 1

            avg_loss = epoch_loss / n_batches
            val_pred = (self.predict(X_val) >= 0.5).astype(float)
            accuracy = np.mean(val_pred == y_val)
            self.training_history["loss"].append(float(avg_loss))
            self.training_history["accuracy"].append(float(accuracy))

            if learning_rate > 0.001 and epoch > 0 and epoch % 30 == 0:
                learning_rate *= 0.5

        self.trained = True
        return {
            "epochs": epochs,
            "final_loss": float(self.training_history["loss"][-1]),
            "final_accuracy": float(self.training_history["accuracy"][-1]),
            "training_samples": len(X_train),
            "validation_samples": len(X_val),
            "history": self.training_history,
        }

    def predict_banknote(self, denomination, serial):
        """Predice si un billete especifico es ilegal."""
        if not self.trained:
            return {
                "probability": 0.0,
                "prediction": "unknown",
                "confidence": 0.0,
                "model_trained": False,
            }
        features = np.array([self._extract_features(denomination, serial)])
        prob = float(self.predict(features)[0, 0])
        return {
            "probability": prob,
            "prediction": "illegal" if prob >= 0.5 else "legal",
            "confidence": abs(prob - 0.5) * 2,
            "model_trained": True,
        }

    def save_weights(self, path):
        """Guarda los pesos del modelo en JSON."""
        data = {
            "layer_sizes": self.layer_sizes,
            "trained": self.trained,
            "weights": [w.tolist() for w in self.weights],
            "biases": [b.tolist() for b in self.biases],
            "history": self.training_history,
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)

    def load_weights(self, path):
        """Carga pesos del modelo desde JSON. Valida arquitectura compatible."""
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r") as f:
                data = json.load(f)
            saved_sizes = data["layer_sizes"]
            if saved_sizes != self.layer_sizes:
                print(f"[NN] Arquitectura incompatible: guardada={saved_sizes}, actual={self.layer_sizes}. Re-entrene el modelo.")
                return False
            self.trained = data["trained"]
            self.weights = [np.array(w) for w in data["weights"]]
            self.biases = [np.array(b) for b in data["biases"]]
            self.training_history = data.get("history", {"loss": [], "accuracy": []})
            return True
        except Exception as e:
            print(f"[NN] Error cargando pesos: {e}")
            return False

    def get_model_info(self):
        """Retorna informacion del modelo."""
        total_params = sum(
            w.size + b.size for w, b in zip(self.weights, self.biases)
        )
        return {
            "architecture": " -> ".join(str(s) for s in self.layer_sizes),
            "total_parameters": total_params,
            "trained": self.trained,
            "last_accuracy": (
                self.training_history["accuracy"][-1]
                if self.training_history["accuracy"]
                else None
            ),
            "last_loss": (
                self.training_history["loss"][-1]
                if self.training_history["loss"]
                else None
            ),
            "epochs_trained": len(self.training_history["loss"]),
        }
