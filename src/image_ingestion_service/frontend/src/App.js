import React, { useState } from 'react';
import DbcImage from "./DbcImage";
import ReplayFrame from "./ReplayFrame";
import './App.css';


const cameraIds = [
  1029, 1096, 1097, 112, 1123, 1124, 113, 114, 115,
  17, 18, 19, 20, 21, 218, 219, 22, 258, 29, 30, 31,
  33, 34, 343, 36, 524, 557, 558, 573, 574, 575, 576,
  577, 578, 579, 658, 659, 660, 661, 67, 683, 684,
  70, 71, 72, 73, 763, 767, 768, 780, 791, 87, 88
];

function App() {
  const [cameraId, setCameraId] = useState('343');

  const handleSelectChange = (e) => {
    setCameraId(e.target.value);
  };


  return (
    <div className="App">
      <div>
        <label>Camera: </label>
        <select value={cameraId} onChange={handleSelectChange}>
          {cameraIds.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
        <input hidden
          type="text"
          value={cameraId}
          onChange={(e) => setCameraId(e.target.value)}
          placeholder="Enter camera ID"
        />
      </div>

      <div style={{ display: "flex", flexDirection: "column" }}>
        <ReplayFrame
          replayTheDay={true}
          cameraId={cameraId}
          apiUrl="http://localhost:8081/api/replay"
          pvcUrl="http://localhost:8081/static/images"
        />
        <ReplayFrame
          replayTheDay={false}
          cameraId={cameraId}
          apiUrl="http://localhost:8081/api/replay"
          s3BucketUrl="http://localhost:9000/test-s3-bucket"
        />
      </div>



      <DbcImage cameraId={cameraId} />

    </div>
  );
}

export default App;