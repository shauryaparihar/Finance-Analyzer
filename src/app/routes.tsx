import { createBrowserRouter } from "react-router";
import { Layout } from "./components/Layout";
import { UploadPage } from "./components/pages/UploadPage";
import { OverviewPage } from "./components/pages/OverviewPage";
import { PredictionsPage } from "./components/pages/PredictionsPage";
import { AnomaliesPage } from "./components/pages/AnomaliesPage";
import { SegmentationPage } from "./components/pages/SegmentationPage";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: Layout,
    children: [
      { index: true, Component: UploadPage },
      { path: "overview", Component: OverviewPage },
      { path: "predictions", Component: PredictionsPage },
      { path: "anomalies", Component: AnomaliesPage },
      { path: "segmentation", Component: SegmentationPage },
    ],
  },
]);
