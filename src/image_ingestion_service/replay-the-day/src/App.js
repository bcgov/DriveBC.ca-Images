import React from "react";
import DbcImage from "./DbcImage";
import ReplayFrame from "./ReplayFrame";

function App() {
  return (
    <div className="App">
      <ReplayFrame
        cameraId="343"
        apiUrl="http://localhost:8080/replay"
        s3BucketUrl="http://localhost:9000/test-s3-bucket"
      />
      <DbcImage cameraId="343" />
      
    </div>
  );
}

export default App;
