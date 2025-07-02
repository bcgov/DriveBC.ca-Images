import React, { useEffect, useState } from "react";

const ReplayTheDay = ({ cameraId }) => {
  const [images, setImages] = useState([]);
  const [currentIdx, setCurrentIdx] = useState(0);
  // const replayTheDayUrl = process.env.REACT_APP_REPLAY_THE_DAY_URL;
  // const replayTheDayS3Url = process.env.REACT_APP_REPLAY_THE_DAY_S3_URL;
  const replayTheDayUrl = "http://localhost:8080/replay";
  const replayTheDayS3Url = "http://localhost:9000/test-s3-bucket";


  useEffect(() => {
    console.log("Fetching images for camera:", cameraId);
    console.log(replayTheDayUrl, replayTheDayS3Url);
    // Fetch image list from API
    fetch(`${replayTheDayUrl}/${cameraId}`)
      .then(res => res.json())
      .then(data => {
        // Sort images by timestamp
        data.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
        setImages(data);
      });
  }, [cameraId]);

  useEffect(() => {
    if (images.length === 0) return;

    const interval = setInterval(() => {
      setCurrentIdx(idx => (idx + 1) % images.length);
    }, 500); // Change frame every 500ms

    return () => clearInterval(interval);
  }, [images]);

  if (images.length === 0) return <div>Loading images...</div>;

  const currentImage = images[currentIdx];
  const imageUrl = `${replayTheDayS3Url}/${currentImage.path}`;

  return (
    <div>
      <h2>Replay: {cameraId}</h2>
      <img
        src={imageUrl}
        alt={`Frame at ${currentImage.timestamp}`}
        style={{ width: "800px", height: "auto", border: "1px solid #ccc" }}
      />
      <p>{new Date(currentImage.timestamp).toLocaleString()}</p>
    </div>
  );
};

export default ReplayTheDay;
