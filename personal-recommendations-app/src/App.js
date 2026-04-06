import './App.css';

function App() {
  return (
    <div className="App">
      <h1>📚 Personal Recommendation System</h1>

      <div style={{ marginTop: "20px" }}>
        <input
          type="text"
          placeholder="Enter topic (e.g. DSA, ML)"
          style={{ padding: "10px", width: "250px" }}
        />
        <br /><br />

        <select style={{ padding: "10px" }}>
          <option>Beginner</option>
          <option>Intermediate</option>
          <option>Advanced</option>
        </select>

        <br /><br />

        <button style={{ padding: "10px 20px" }}>
          Get Recommendations
        </button>
      </div>
    </div>
  );
}

export default App;