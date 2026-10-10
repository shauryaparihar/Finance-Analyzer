import { createBrowserRouter, Navigate } from "react-router";
import { Layout } from "./components/Layout";
import { RequireAuth } from "./components/RequireAuth";
import { AuthPage } from "./components/pages/AuthPage";
import { CategoriesPage } from "./components/pages/CategoriesPage";
import { ForecastPage } from "./components/pages/ForecastPage";
import { OverviewPage } from "./components/pages/OverviewPage";
import { UnusualPage } from "./components/pages/UnusualPage";
import { UploadPage } from "./components/pages/UploadPage";

export const router = createBrowserRouter([
  { path: "/login", element: <AuthPage mode="login" /> },
  { path: "/register", element: <AuthPage mode="register" /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <Layout />
      </RequireAuth>
    ),
    children: [
      { index: true, Component: UploadPage },
      { path: "overview", Component: OverviewPage },
      { path: "forecast", Component: ForecastPage },
      { path: "unusual", Component: UnusualPage },
      { path: "categories", Component: CategoriesPage },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
