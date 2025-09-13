import pandas as pd
import random

class Recommender:
    def __init__(self, topic_graph_path, student_data_path, history_path, resources_path, study_plan_path=None):
        self.topic_graph = pd.read_csv(topic_graph_path)
        self.student_data = pd.read_csv(student_data_path)
        self.history = pd.read_csv(history_path)
        self.resources = pd.read_csv(resources_path)
        self.study_plan = pd.read_csv(study_plan_path) if study_plan_path else pd.DataFrame()

        self.student_data['student_id'] = self.student_data['student_id'].astype(int)
        self.history['student_id'] = self.history['student_id'].astype(int)

    # ---------------- Utility ----------------
    def list_students(self):
        return self.student_data['student_id'].tolist()

    def get_completed_topics(self, student_id):
        record = self.student_data[self.student_data['student_id'] == student_id]
        if record.empty or 'completed_topics' not in record.columns:
            return []
        topics = record['completed_topics'].values[0]
        return topics.split(";") if pd.notna(topics) else []

    def generate_confidence_scores(self, student_id):
        completed = self.get_completed_topics(student_id)
        for topic in completed:
            exists = ((self.history['student_id'] == student_id) & (self.history['topic'] == topic)).any()
            if not exists:
                conf = random.randint(50, 100)
                self.history.loc[len(self.history)] = [student_id, topic, conf]
        self.history.to_csv("data/history.csv", index=False)
        return self.history[self.history['student_id'] == student_id]

    # ---------------- URL Cleaner ----------------
    def clean_url(self, url):
        if not url:
            return ""
        url = url.strip()
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return "https://" + url

    # ---------------- Recommendations ----------------
    def get_next_recommendations(self, student_id):
        student_history = self.generate_confidence_scores(student_id)
        completed = self.get_completed_topics(student_id)
        rec_topics = set()

        for _, row in self.topic_graph.iterrows():
            topic = row['topic']
            relation = row.get('relation', '')
            related = row.get('related_topic', '')

            if topic in completed:
                continue

            conf_record = student_history.loc[student_history['topic'] == topic, 'confidence']
            conf = int(conf_record.values[0]) if not conf_record.empty else 0

            if relation == 'prerequisite' and conf < 50 and related not in completed:
                rec_topics.add(related)

            if relation != 'prerequisite' or related in completed:
                rec_topics.add(topic)

        recommendations = []
        for topic in rec_topics:
            res = self.resources[self.resources['topic'] == topic]
            conf_record = student_history.loc[student_history['topic'] == topic, 'confidence']
            conf_val = int(conf_record.values[0]) if not conf_record.empty else 0

            youtube_link = ""
            docs_link = ""
            if not res.empty:
                if pd.notna(res['youtube_link'].values[0]):
                    youtube_link = self.clean_url(res['youtube_link'].values[0])
                if pd.notna(res['documentation_link'].values[0]):
                    docs_link = self.clean_url(res['documentation_link'].values[0])

            recommendations.append({
                "topic": topic,
                "confidence": conf_val,
                "youtube": youtube_link,   # matches template rec.youtube
                "docs": docs_link,         # matches template rec.docs
                "strategy": "focus"
            })

        recommendations.sort(key=lambda x: x['confidence'])
        return recommendations

    # ---------------- Adaptive Transform ----------------
    def adaptive_transform(self, student_id, recommendations):
        recommendations.sort(key=lambda x: x['confidence'])
        for r in recommendations:
            r['strategy'] = 'focus' if r['confidence'] < 80 else 'review'
        return recommendations

    # ---------------- Progress ----------------
    def get_progress(self, student_id):
        student_history = self.generate_confidence_scores(student_id)
        if student_history.empty:
            return 0
        return round(student_history['confidence'].mean(), 2)

    def expected_confidence_gain(self, student_id, topic):
        student_history = self.generate_confidence_scores(student_id)
        current = student_history.loc[student_history['topic'] == topic, 'confidence']
        curr_val = int(current.values[0]) if not current.empty else 0
        gain = random.randint(5, 15)
        return min(curr_val + gain, 100)

    def update_confidence(self, student_id, topic, gain):
        idx = self.history[(self.history['student_id'] == student_id) & (self.history['topic'] == topic)].index
        if not idx.empty:
            self.history.loc[idx, 'confidence'] = min(self.history.loc[idx, 'confidence'] + gain, 100)
        else:
            self.history.loc[len(self.history)] = [student_id, topic, min(gain, 100)]
        self.history.to_csv("data/history.csv", index=False)

    # ---------------- Study Plan ----------------
    def get_study_plan(self):
        if not self.study_plan.empty:
            return self.study_plan.to_dict(orient="records")
        return []

    # ---------------- Badges ----------------
    def get_badges(self, student_id):
        student_history = self.generate_confidence_scores(student_id)
        badges = []
        strong_count = (student_history['confidence'] >= 80).sum()
        weak_count = (student_history['confidence'] < 50).sum()
        high_achiever = (student_history['confidence'] >= 90).any()

        if strong_count >= 3:
            badges.append("Consistency Star ⭐")
        if weak_count == 0:
            badges.append("Improvement Badge 📈")
        if high_achiever:
            badges.append("High Achiever 🏆")

        return badges

    # ---------------- Save ----------------
    def save(self, student_data_path="data/student_data.csv", history_path="data/history.csv"):
        self.student_data.to_csv(student_data_path, index=False)
        self.history.to_csv(history_path, index=False)
        if not self.study_plan.empty:
            self.study_plan.to_csv("data/study_plan.csv", index=False)
