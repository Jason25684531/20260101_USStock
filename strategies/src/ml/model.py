"""
機器學習模型模塊
支持 XGBoost 和隨機森林進行股票預測
"""
import os
import pickle
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Literal
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, 
    f1_score, classification_report, confusion_matrix
)
from sklearn.model_selection import train_test_split
import warnings
warnings.filterwarnings('ignore')

# 嘗試導入 XGBoost
try:
    from xgboost import XGBClassifier
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    print("⚠️  XGBoost 未安裝，將使用 RandomForest")

# 嘗試導入 matplotlib
try:
    import matplotlib
    matplotlib.use('Agg')  # 非交互式後端，避免 GUI 錯誤
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("⚠️  matplotlib 未安裝，將無法生成圖表")


class StrategyModel:
    """
    交易策略機器學習模型
    支持 XGBoost 和 RandomForest 分類器預測股票未來走勢
    """
    
    def __init__(
        self,
        model_type: Literal['xgboost', 'randomforest'] = 'xgboost',
        n_estimators: int = 300,
        max_depth: Optional[int] = 5,
        learning_rate: float = 0.01,
        min_samples_split: int = 20,
        min_samples_leaf: int = 10,
        random_state: int = 42,
        reg_lambda: float = 1.0,
        gamma: float = 0.1,
        **kwargs
    ):
        """
        初始化模型
        
        Args:
            model_type: 模型類型 ('xgboost' 或 'randomforest')
            n_estimators: 樹的數量
            max_depth: 樹的最大深度
            learning_rate: 學習率（僅 XGBoost）
            min_samples_split: 分割內部節點所需的最小樣本數（僅 RF）
            min_samples_leaf: 葉節點所需的最小樣本數（僅 RF）
            random_state: 隨機種子
            reg_lambda: L2 正則化參數（僅 XGBoost）
            gamma: 最小損失降低閾值（僅 XGBoost）
            **kwargs: 其他模型參數
        """
        self.model_type = model_type
        
        # 如果選擇 XGBoost 但未安裝，自動回退到 RandomForest
        if model_type == 'xgboost' and not XGBOOST_AVAILABLE:
            print("⚠️  XGBoost 不可用，回退到 RandomForest")
            model_type = 'randomforest'
            self.model_type = 'randomforest'
        
        if model_type == 'xgboost':
            # 使用 XGBoost + 正則化
            self.model = XGBClassifier(
                n_estimators=n_estimators,
                max_depth=max_depth,
                learning_rate=learning_rate,
                reg_lambda=reg_lambda,
                gamma=gamma,
                random_state=random_state,
                n_jobs=-1,
                eval_metric='logloss',
                early_stopping_rounds=10,
                use_label_encoder=False,
                **kwargs
            )
            print(f"✅ 使用 XGBoost 模型 (n_estimators={n_estimators}, max_depth={max_depth}, "
                  f"lr={learning_rate}, lambda={reg_lambda}, gamma={gamma})")
        else:
            # 使用 RandomForest
            self.model = RandomForestClassifier(
                n_estimators=n_estimators,
                max_depth=max_depth,
                min_samples_split=min_samples_split,
                min_samples_leaf=min_samples_leaf,
                random_state=random_state,
                n_jobs=-1,
                class_weight='balanced',
                **kwargs
            )
            print(f"✅ 使用 RandomForest 模型 (n_estimators={n_estimators}, max_depth={max_depth})")
        
        self.feature_names = None
        self.feature_importance = None
        self.training_metrics = {}
        self.is_trained = False
    
    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_test: Optional[pd.DataFrame] = None,
        y_test: Optional[pd.Series] = None
    ) -> dict:
        """
        訓練模型
        
        Args:
            X_train: 訓練特徵
            y_train: 訓練標籤
            X_test: 測試特徵（可選）
            y_test: 測試標籤（可選）
            
        Returns:
            包含訓練和測試指標的字典
        """
        model_name = "XGBoost" if self.model_type == 'xgboost' else "隨機森林"
        print(f"\n🤖 開始訓練{model_name}模型...")
        print(f"   訓練樣本: {len(X_train)}")
        print(f"   特徵數量: {X_train.shape[1]}")
        print(f"   正樣本比例: {y_train.mean():.2%}")
        
        # 保存特徵名稱
        self.feature_names = X_train.columns.tolist()
        
        # 處理 XGBoost 的類別不平衡
        if self.model_type == 'xgboost':
            # 計算 scale_pos_weight = (負樣本數 / 正樣本數)
            n_pos = (y_train == 1).sum()
            n_neg = (y_train == 0).sum()
            if n_pos > 0:
                scale_pos_weight = n_neg / n_pos
                self.model.set_params(scale_pos_weight=scale_pos_weight)
                print(f"   ⚖️  設置類別權重: scale_pos_weight={scale_pos_weight:.2f}")
        
        # 訓練模型（包含 Early Stopping）
        start_time = datetime.now()
        
        if self.model_type == 'xgboost' and X_test is not None and y_test is not None:
            # XGBoost Early Stopping：從訓練集分出 20% 作為驗證集
            X_tr, X_val, y_tr, y_val = train_test_split(
                X_train, y_train, test_size=0.2, random_state=42, stratify=y_train
            )
            print(f"   🛡️ Early Stopping: 訓練={len(X_tr)}, 驗證={len(X_val)}, patience=10")
            
            self.model.fit(
                X_tr, y_tr,
                eval_set=[(X_val, y_val)],
                verbose=False
            )
            # 記錄實際使用的迭代次數
            best_iteration = getattr(self.model, 'best_iteration', self.model.n_estimators)
            print(f"   ✅ 最佳迭代次數: {best_iteration}")
        else:
            self.model.fit(X_train, y_train)
        
        training_time = (datetime.now() - start_time).total_seconds()
        
        print(f"   ✅ 訓練完成 (耗時: {training_time:.2f}秒)")
        
        # 獲取特徵重要性
        self.feature_importance = pd.DataFrame({
            'feature': self.feature_names,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=False)
        
        # 在訓練集上評估
        y_train_pred = self.model.predict(X_train)
        train_metrics = self._calculate_metrics(y_train, y_train_pred, "訓練集")
        
        # 在測試集上評估（如果提供）
        test_metrics = {}
        if X_test is not None and y_test is not None:
            print(f"\n   測試樣本: {len(X_test)}")
            y_test_pred = self.model.predict(X_test)
            test_metrics = self._calculate_metrics(y_test, y_test_pred, "測試集")
        
        # 保存指標
        self.training_metrics = {
            'train': train_metrics,
            'test': test_metrics,
            'training_time': training_time,
            'n_features': X_train.shape[1],
            'n_samples': len(X_train)
        }
        
        self.is_trained = True
        
        # 顯示前10個最重要的特徵
        print("\n📊 前10個最重要的特徵:")
        for idx, row in self.feature_importance.head(10).iterrows():
            print(f"   {row['feature']:.<30} {row['importance']:.4f}")
        
        return self.training_metrics
    
    def _calculate_metrics(
        self,
        y_true: pd.Series,
        y_pred: np.ndarray,
        dataset_name: str
    ) -> dict:
        """
        計算分類指標
        
        Args:
            y_true: 真實標籤
            y_pred: 預測標籤
            dataset_name: 數據集名稱（用於打印）
            
        Returns:
            指標字典
        """
        accuracy = accuracy_score(y_true, y_pred)
        precision = precision_score(y_true, y_pred, zero_division=0)
        recall = recall_score(y_true, y_pred, zero_division=0)
        f1 = f1_score(y_true, y_pred, zero_division=0)
        
        print(f"\n   {dataset_name}表現:")
        print(f"      準確率 (Accuracy):  {accuracy:.4f}")
        print(f"      精確率 (Precision): {precision:.4f}")
        print(f"      召回率 (Recall):    {recall:.4f}")
        print(f"      F1分數:             {f1:.4f}")
        
        metrics = {
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'f1': f1,
            'confusion_matrix': confusion_matrix(y_true, y_pred).tolist()
        }
        
        return metrics
    
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        預測類別
        
        Args:
            X: 特徵 DataFrame
            
        Returns:
            預測類別 (0 或 1)
        """
        if not self.is_trained:
            raise ValueError("模型尚未訓練，請先調用 train() 方法")
        
        return self.model.predict(X)
    
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        預測概率
        
        Args:
            X: 特徵 DataFrame
            
        Returns:
            每個類別的概率 [P(0), P(1)]
        """
        if not self.is_trained:
            raise ValueError("模型尚未訓練，請先調用 train() 方法")
        
        return self.model.predict_proba(X)
    
    def get_prediction_confidence(self, X: pd.DataFrame) -> float:
        """
        獲取預測置信度（類別1的概率）
        
        Args:
            X: 特徵 DataFrame（單個樣本）
            
        Returns:
            上漲概率 (0-1)
        """
        proba = self.predict_proba(X)
        # 返回類別1（上漲）的概率
        return proba[0, 1]
    
    def save(self, filepath: str = None):
        """
        保存模型到文件
        
        Args:
            filepath: 保存路徑，默認為 data/model.pkl
        """
        if not self.is_trained:
            raise ValueError("模型尚未訓練，無法保存")
        
        if filepath is None:
            # 默認保存到 data/ 目錄
            project_root = Path(__file__).parent.parent.parent.parent
            data_dir = project_root / 'data'
            data_dir.mkdir(exist_ok=True)
            filepath = data_dir / 'model.pkl'
        
        filepath = Path(filepath)
        
        # 保存模型和元數據
        model_data = {
            'model': self.model,
            'model_type': self.model_type,
            'feature_names': self.feature_names,
            'feature_importance': self.feature_importance,
            'training_metrics': self.training_metrics,
            'trained_at': datetime.now().isoformat()
        }
        
        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)
        
        print(f"\n✅ 模型已保存到: {filepath}")
    
    @classmethod
    def load(cls, filepath: str = None) -> 'StrategyModel':
        """
        從文件加載模型
        
        Args:
            filepath: 模型文件路徑，默認為 data/model.pkl
            
        Returns:
            加載的 StrategyModel 實例
        """
        if filepath is None:
            # 默認從 data/ 目錄加載
            project_root = Path(__file__).parent.parent.parent.parent
            filepath = project_root / 'data' / 'model.pkl'
        
        filepath = Path(filepath)
        
        if not filepath.exists():
            raise FileNotFoundError(f"模型文件不存在: {filepath}")
        
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)
        
        # 創建新實例
        instance = cls()
        instance.model = model_data['model']
        instance.model_type = model_data.get('model_type', 'randomforest')  # 向後兼容
        instance.feature_names = model_data['feature_names']
        instance.feature_importance = model_data['feature_importance']
        instance.training_metrics = model_data['training_metrics']
        instance.is_trained = True
        
        trained_at = model_data.get('trained_at', 'unknown')
        print(f"✅ 模型已加載: {filepath}")
        print(f"   訓練時間: {trained_at}")
        print(f"   特徵數量: {len(instance.feature_names)}")
        
        return instance
    
    def get_feature_importance(self, top_n: int = 20) -> pd.DataFrame:
        """
        獲取特徵重要性排名
        
        Args:
            top_n: 返回前N個最重要的特徵
            
        Returns:
            特徵重要性 DataFrame
        """
        if self.feature_importance is None:
            raise ValueError("模型尚未訓練")
        
        return self.feature_importance.head(top_n)
    
    def save_feature_importance_plot(self, filepath: str = None, top_n: int = 15) -> str:
        """
        保存特徵重要性長條圖到文件
        
        Args:
            filepath: 保存路徑，默認為 data/reports/feature_importance.png
            top_n: 顯示前N個最重要的特徵
            
        Returns:
            保存的文件路徑
        """
        if not MATPLOTLIB_AVAILABLE:
            print("⚠️  matplotlib 未安裝，無法生成特徵重要性圖表")
            return ""
        
        if self.feature_importance is None:
            raise ValueError("模型尚未訓練，無法生成圖表")
        
        if filepath is None:
            project_root = Path(__file__).parent.parent.parent.parent
            report_dir = project_root / 'data' / 'reports'
            report_dir.mkdir(parents=True, exist_ok=True)
            filepath = report_dir / 'feature_importance.png'
        
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        # 取前 N 個特徵
        top_features = self.feature_importance.head(top_n).copy()
        top_features = top_features.sort_values('importance', ascending=True)
        
        # 繪製長條圖
        fig, ax = plt.subplots(figsize=(10, max(6, top_n * 0.4)))
        bars = ax.barh(
            top_features['feature'], 
            top_features['importance'],
            color='#2196F3',
            edgecolor='#1565C0',
            alpha=0.85
        )
        
        ax.set_xlabel('Importance Score', fontsize=12)
        ax.set_title(f'Top {top_n} Feature Importance ({self.model_type.upper()})', fontsize=14, fontweight='bold')
        ax.tick_params(axis='y', labelsize=10)
        
        # 在每個長條上標注數值
        for bar, val in zip(bars, top_features['importance']):
            ax.text(bar.get_width() + 0.001, bar.get_y() + bar.get_height() / 2,
                    f'{val:.4f}', va='center', fontsize=9)
        
        plt.tight_layout()
        fig.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)
        
        print(f"\n📊 特徵重要性圖表已保存: {filepath}")
        return str(filepath)
    
    def plot_prediction_accuracy(
        self,
        X: pd.DataFrame,
        y_actual_return: pd.Series,
        filepath: str = None
    ) -> str:
        """
        繪製 Predicted Probability vs Actual 5-day Return 散點圖
        
        用於驗證模型信心度是否與實際收益相關：
        - X 軸: 模型預測上漲概率 (0-1)
        - Y 軸: 實際未來 5 天報酬率
        
        Args:
            X: 特徵 DataFrame（與模型訓練時一致的特徵欄位）
            y_actual_return: 對應的實際未來收益率 Series
            filepath: 保存路徑，默認 data/reports/prediction_accuracy.png
            
        Returns:
            保存的文件路徑（空字串如果 matplotlib 不可用）
        """
        if not MATPLOTLIB_AVAILABLE:
            print("⚠️  matplotlib 未安裝，無法生成預測準確度圖表")
            return ""
        
        if not self.is_trained:
            raise ValueError("模型尚未訓練，無法生成圖表")
        
        if filepath is None:
            project_root = Path(__file__).parent.parent.parent.parent
            report_dir = project_root / 'data' / 'reports'
            report_dir.mkdir(parents=True, exist_ok=True)
            filepath = report_dir / 'prediction_accuracy.png'
        
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        # 預測概率
        probas = self.predict_proba(X)
        up_prob = probas[:, 1]
        actual = y_actual_return.values
        
        # 散點圖 + 趨勢線
        fig, ax = plt.subplots(figsize=(10, 7))
        
        # 根據方向上色：正收益=綠，負收益=紅
        colors = np.where(actual >= 0, '#4CAF50', '#F44336')
        ax.scatter(up_prob, actual * 100, c=colors, alpha=0.35, s=15, edgecolors='none')
        
        # 添加趨勢線
        try:
            z = np.polyfit(up_prob, actual * 100, 1)
            p = np.poly1d(z)
            x_line = np.linspace(up_prob.min(), up_prob.max(), 100)
            ax.plot(x_line, p(x_line), color='#2196F3', linewidth=2,
                    label=f'Trend: y={z[0]:.2f}x + {z[1]:.2f}')
        except Exception:
            pass
        
        # 參考線
        ax.axhline(0, color='black', linewidth=0.5)
        ax.axvline(0.5, color='gray', linewidth=0.5, linestyle='--')
        
        # 分區標籤
        ax.axvline(0.7, color='green', linewidth=0.8, linestyle='--', alpha=0.5, label='Buy Threshold (0.7)')
        ax.axvline(0.3, color='red', linewidth=0.8, linestyle='--', alpha=0.5, label='Sell Threshold (0.3)')
        
        ax.set_xlabel('Predicted Up Probability', fontsize=12)
        ax.set_ylabel('Actual 5-day Return (%)', fontsize=12)
        ax.set_title('Model Calibration: Predicted Probability vs Actual Return', fontsize=14, fontweight='bold')
        ax.legend(loc='upper left', fontsize=9)
        ax.grid(True, alpha=0.2)
        
        # 統計資訊
        corr = np.corrcoef(up_prob, actual)[0, 1]
        textstr = f'Correlation: {corr:.3f}\nSamples: {len(actual)}'
        ax.text(0.98, 0.02, textstr, transform=ax.transAxes,
                fontsize=10, verticalalignment='bottom', horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        
        plt.tight_layout()
        fig.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)
        
        print(f"\n📊 預測準確度圖表已保存: {filepath}")
        print(f"   預測概率 vs 實際回報 相關性: {corr:.3f}")
        return str(filepath)
    
    def generate_report(self) -> str:
        """
        生成模型訓練報告
        
        Returns:
            報告文本
        """
        if not self.is_trained:
            return "模型尚未訓練，無法生成報告"
        
        report = []
        report.append("=" * 70)
        report.append(" 📊 機器學習模型訓練報告")
        report.append("=" * 70)
        report.append("")
        
        # 基本信息
        report.append("【模型配置】")
        if self.model_type == 'xgboost':
            report.append(f"  算法: XGBoost (Gradient Boosting)")
            report.append(f"  樹的數量: {self.model.n_estimators}")
            report.append(f"  最大深度: {self.model.max_depth}")
            report.append(f"  學習率: {self.model.learning_rate}")
            report.append(f"  L2正則化 (lambda): {getattr(self.model, 'reg_lambda', 'N/A')}")
            report.append(f"  最小損失降低 (gamma): {getattr(self.model, 'gamma', 'N/A')}")
            report.append(f"  Early Stopping: 已啟用 (patience=10)")
        else:
            report.append(f"  算法: 隨機森林 (Random Forest)")
            report.append(f"  樹的數量: {self.model.n_estimators}")
            report.append(f"  最大深度: {self.model.max_depth}")
        report.append("")
        
        # 訓練信息
        metrics = self.training_metrics
        report.append("【訓練信息】")
        report.append(f"  樣本數量: {metrics['n_samples']}")
        report.append(f"  特徵數量: {metrics['n_features']}")
        report.append(f"  訓練時間: {metrics['training_time']:.2f}秒")
        report.append("")
        
        # 訓練集表現
        train_metrics = metrics['train']
        report.append("【訓練集表現】")
        report.append(f"  準確率: {train_metrics['accuracy']:.4f}")
        report.append(f"  精確率: {train_metrics['precision']:.4f}")
        report.append(f"  召回率: {train_metrics['recall']:.4f}")
        report.append(f"  F1分數: {train_metrics['f1']:.4f}")
        report.append("")
        
        # 測試集表現
        if metrics['test']:
            test_metrics = metrics['test']
            report.append("【測試集表現】")
            report.append(f"  準確率: {test_metrics['accuracy']:.4f}")
            report.append(f"  精確率: {test_metrics['precision']:.4f}")
            report.append(f"  召回率: {test_metrics['recall']:.4f}")
            report.append(f"  F1分數: {test_metrics['f1']:.4f}")
            report.append("")
        
        # 前10個重要特徵
        report.append("【前10個最重要特徵】")
        for idx, row in self.feature_importance.head(10).iterrows():
            report.append(f"  {idx+1}. {row['feature']:.<30} {row['importance']:.4f}")
        report.append("")
        
        report.append("=" * 70)
        
        return "\n".join(report)
