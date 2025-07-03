import React from "react";
import ReplayTheDay from "./ReplayTheDay";
import DbcImage from "./DbcImage";

function App() {
  return (
    <div className="App">
      <ReplayTheDay cameraId="343" />
      <DbcImage cameraId="343" />
    </div>
  );
}

export default App;
