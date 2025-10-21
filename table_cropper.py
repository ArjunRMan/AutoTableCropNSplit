import sys
import os
import cv2
import numpy as np
from PIL import Image
import json

class AdvancedTableCropper:
    def __init__(self):
        self.total_cols = 32
        self.total_rows = 17

    def detect_table_corners(self, image):
        """
        Detect table corners using contour detection and edge analysis.
    
        Args:
            image: OpenCV image (BGR format)
    
        Returns:
            corners: List of 4 corner points [(x,y), ...]
        """
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Apply Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Edge detection
        edges = cv2.Canny(blurred, 50, 150, apertureSize=3)
        
        # Morphological operations to close gaps
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        
        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Find the largest rectangular contour
        best_contour = None
        max_area = 0
        
        for contour in contours:
            # Approximate contour to polygon
            epsilon = 0.02 * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)
            
            # Check if it's a quadrilateral and has significant area
            if len(approx) == 4:
                area = cv2.contourArea(contour)
                if area > max_area and area > (image.shape[0] * image.shape[1] * 0.1):
                    max_area = area
                    best_contour = approx
        
        if best_contour is not None:
            # Convert to simple list of points
            corners = []
            for point in best_contour:
                corners.append((point[0][0], point[0][1]))
            
            # Sort corners: top-left, top-right, bottom-right, bottom-left
            corners = self.sort_corners(corners)
            return corners
        
        # Fallback: use image boundaries with some margin
        h, w = image.shape[:2]
        margin = min(w, h) * 0.05
        return [
            (margin, margin),  # top-left
            (w - margin, margin),  # top-right
            (w - margin, h - margin),  # bottom-right
            (margin, h - margin)  # bottom-left
        ]
    
    def sort_corners(self, corners):
        """
        Sort corners in order: top-left, top-right, bottom-right, bottom-left
        """
        # Calculate center point
        cx = sum(p[0] for p in corners) / 4
        cy = sum(p[1] for p in corners) / 4
        
        # Sort by angle from center
        def angle_from_center(point):
            return np.arctan2(point[1] - cy, point[0] - cx)
        
        sorted_corners = sorted(corners, key=angle_from_center)
        
        # Ensure we start with top-left corner
        # Find corner with minimum distance to (0,0)
        min_dist = float('inf')
        start_idx = 0
        for i, corner in enumerate(sorted_corners):
            dist = corner[0]**2 + corner[1]**2
            if dist < min_dist:
                min_dist = dist
                start_idx = i
        
        # Reorder starting from top-left
        reordered = sorted_corners[start_idx:] + sorted_corners[:start_idx]
        return reordered
    
    def apply_perspective_correction(self, image, corners, target_width=1240, target_height=850):
        """
        Apply perspective correction using the detected corners.
        Moves right corners 30px to the right before correction to capture 31st column fully.
        
        Args:
            image: OpenCV image
            corners: List of 4 corner points
            target_width: Desired width of corrected image
            target_height: Desired height of corrected image
            
        Returns:
            corrected_image: Perspective-corrected image with 31 columns + margin
        """
        # Adjust right corners by moving them 30px to the right to capture 31st column
        adjusted_corners = []
        for i, corner in enumerate(corners):
            if i == 1 or i == 2:  # Right corners (top-right and bottom-right)
                # Move right corners 30px to the right
                adjusted_corner = (corner[0] + 30, corner[1])
                adjusted_corners.append(adjusted_corner)
                print(f"Adjusted right corner {i+1}: {corner} → {adjusted_corner}")
            else:
                adjusted_corners.append(corner)
        
        # Source corners (adjusted to capture 31st column)
        src_points = np.float32(adjusted_corners)
        
        # Calculate margin to add AFTER the 31st column
        # We want to ensure all 31 columns fit, then add 10% or minimum 50px margin
        margin_percent = 0.10  # 10% (increased from 5% to ensure 31st column is fully visible)
        margin_pixels = max(50, int(target_width * margin_percent))  # At least 50px or 10%
        
        # Final width includes all columns plus margin after 31st column
        final_width = target_width + margin_pixels
        
        # Destination corners (rectangle) - ensures full table + margin
        dst_points = np.float32([
            [0, 0],  # top-left
            [final_width, 0],  # top-right (includes margin after 31st column)
            [final_width, target_height],  # bottom-right
            [0, target_height]  # bottom-left
        ])
        
        # Calculate perspective transformation matrix
        matrix = cv2.getPerspectiveTransform(src_points, dst_points)
        
        # Apply perspective correction with Lanczos interpolation
        # This gives us the full table with margin already included
        corrected = cv2.warpPerspective(
            image, 
            matrix, 
            (final_width, target_height),
            flags=cv2.INTER_LANCZOS4
        )
        
        # No need to crop - we've already included the proper margin in the transformation
        return corrected
    
    def calculate_cell_dimensions(self, image_width, image_height):
        """Calculate cell dimensions based on table structure."""
        cell_width = image_width // self.total_cols
        cell_height = image_height // self.total_rows
        return cell_width, cell_height
    
    def remove_first_column(self, image, cell_width):
        """
        Remove the first column (labels) more accurately.
        """
        # Add small margin to ensure complete removal
        margin = int(cell_width * 0.1)  # 10% margin
        crop_x = cell_width + margin
        
        h, w = image.shape[:2]
        if crop_x >= w:
            crop_x = w // self.total_cols  # Fallback to basic calculation
            
        return image[:, crop_x:]
    
    def crop_left_26_percent(self, image):
        """
        Crop 26% from the left side of the image before splitting.
        """
        h, w = image.shape[:2]
        crop_x = int(w * 0.26)  # 26% from left
        return image[:, crop_x:]
    
    def split_into_equal_parts(self, image):
        """
        Split image into two equal parts by rows.
        """
        h, w = image.shape[:2]
        
        # Calculate split point for equal division
        # For 17 rows: first part gets 8 rows, second part gets 9 rows
        cell_height = h // self.total_rows
        split_point = cell_height * 8  # After 8 rows
        
        part1 = image[:split_point, :]  # Rows 1-8
        part2 = image[split_point:, :]   # Rows 9-17
        
        return part1, part2
    
    def process_image(self, input_path, output_dir=None, return_images=False):
        """
        Main processing function with perspective correction.

        Args:
            input_path (str): path to source image
            output_dir (str|None): where to save outputs. If None and return_images is False,
                a default ./output directory is used. If return_images is True, nothing is saved
                unless an explicit output_dir is provided.
            return_images (bool): when True, return PIL Images in-memory instead of (or in addition to) saving.

        Returns:
            - if return_images is True: dict with PIL Images {cropped_table, part1, part2, metadata}
            - else: True on success, False on failure
        """
        try:
            print(f"Loading image: {input_path}")
            
            # Load image with OpenCV for processing
            cv_image = cv2.imread(input_path)
            if cv_image is None:
                raise ValueError(f"Could not load image: {input_path}")
            
            print(f"Original image dimensions: {cv_image.shape[1]} x {cv_image.shape[0]}")
            
            # Set up output directory only if we intend to save
            should_save = output_dir is not None or (output_dir is None and not return_images)
            if should_save:
                if output_dir is None:
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    output_dir = os.path.join(script_dir, "output")
                os.makedirs(output_dir, exist_ok=True)
            
            # Get base filename
            input_filename = os.path.splitext(os.path.basename(input_path))[0]
            
            # Step 1: Detect table corners
            print("Detecting table corners...")
            corners = self.detect_table_corners(cv_image)
            print(f"Detected corners: {corners}")
            
            # Corner visualization (always build in-memory; save if enabled)
            corner_vis = cv_image.copy()
            for i, corner in enumerate(corners):
                cv2.circle(corner_vis, (int(corner[0]), int(corner[1])), 10, (0, 0, 255), -1)
                cv2.putText(corner_vis, str(i+1), (int(corner[0])+15, int(corner[1])+15), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            if should_save:
                corner_vis_path = os.path.join(output_dir, f"{input_filename}_corners.png")
                cv2.imwrite(corner_vis_path, corner_vis)
                print(f"Corner detection saved: {corner_vis_path}")
            
            # Step 2: Apply perspective correction
            print("Applying perspective correction...")
            # Calculate target dimensions based on aspect ratio
            target_width = 1240  # Approximate width for 31 columns
            target_height = 850  # Approximate height for 17 rows
            
            corrected_image = self.apply_perspective_correction(
                cv_image, corners, target_width, target_height
            )
            print(f"Perspective corrected dimensions: {corrected_image.shape[1]} x {corrected_image.shape[0]}")
            
            # Save perspective corrected image (optional)
            if should_save:
                corrected_path = os.path.join(output_dir, f"{input_filename}_perspective_corrected.png")
                cv2.imwrite(corrected_path, corrected_image)
                print(f"Perspective corrected image saved: {corrected_path}")
            
            # Step 3: Calculate cell dimensions on corrected image
            cell_width, cell_height = self.calculate_cell_dimensions(
                corrected_image.shape[1], corrected_image.shape[0]
            )
            print(f"Calculated cell dimensions: {cell_width} x {cell_height}")
            
            # Step 4: Remove first column
            print("Removing first column (labels)...")
            cropped_image = self.remove_first_column(corrected_image, cell_width)
            
            # Save cropped table (optional)
            if should_save:
                cropped_path = os.path.join(output_dir, f"{input_filename}_cropped_table.png")
                cv2.imwrite(cropped_path, cropped_image)
                print(f"Cropped table saved: {cropped_path}")
            
            # Step 5: Crop 26% from left before splitting
            print("Cropping 26% from left side...")
            left_cropped_image = self.crop_left_26_percent(cropped_image)
            
            # Save left-cropped table (optional)
            if should_save:
                left_cropped_path = os.path.join(output_dir, f"{input_filename}_left_cropped.png")
                cv2.imwrite(left_cropped_path, left_cropped_image)
                print(f"Left-cropped table saved: {left_cropped_path}")
            
            # Step 6: Split into equal parts
            print("Splitting into equal parts...")
            part1, part2 = self.split_into_equal_parts(left_cropped_image)
            
            # Save parts (optional)
            if should_save:
                part1_path = os.path.join(output_dir, f"{input_filename}_part1_rows1-8.png")
                part2_path = os.path.join(output_dir, f"{input_filename}_part2_rows9-17.png")
                cv2.imwrite(part1_path, part1)
                cv2.imwrite(part2_path, part2)
                print(f"Part 1 (rows 1-8) saved: {part1_path}")
                print(f"Part 2 (rows 9-17) saved: {part2_path}")
            
            # Build processing metadata
            metadata = {
                "original_dimensions": f"{cv_image.shape[1]} x {cv_image.shape[0]}",
                "corrected_dimensions": f"{corrected_image.shape[1]} x {corrected_image.shape[0]}",
                "detected_corners": [[int(x), int(y)] for x, y in corners],
                "cell_dimensions": f"{cell_width} x {cell_height}",
            }

            # Optional save processing metadata and record output file names
            if should_save:
                metadata["output_files"] = {}
                if 'corner_vis_path' in locals():
                    metadata["output_files"]["corners_visualization"] = os.path.basename(corner_vis_path)
                if 'corrected_path' in locals():
                    metadata["output_files"]["perspective_corrected"] = os.path.basename(corrected_path)
                if 'cropped_path' in locals():
                    metadata["output_files"]["cropped_table"] = os.path.basename(cropped_path)
                if 'left_cropped_path' in locals():
                    metadata["output_files"]["left_cropped"] = os.path.basename(left_cropped_path)
                if 'part1_path' in locals():
                    metadata["output_files"]["part1"] = os.path.basename(part1_path)
                if 'part2_path' in locals():
                    metadata["output_files"]["part2"] = os.path.basename(part2_path)
                metadata_path = os.path.join(output_dir, f"{input_filename}_metadata.json")
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
            
            if return_images:
                # Convert OpenCV (BGR) arrays to PIL Images
                def to_pil(bgr_img):
                    rgb = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2RGB)
                    return Image.fromarray(rgb)
                return {
                    "original": to_pil(cv_image),
                    "corners_vis": to_pil(corner_vis),
                    "perspective_corrected": to_pil(corrected_image),
                    "cropped_table": to_pil(cropped_image),
                    "left_cropped": to_pil(left_cropped_image),
                    "part1": to_pil(part1),
                    "part2": to_pil(part2),
                    "metadata": metadata,
                }
            else:
                if should_save:
                    print("\n" + "="*60)
                    print("PROCESSING COMPLETED SUCCESSFULLY!")
                    print("="*60)
                return True
            
        except Exception as e:
            print(f"\n❌ Error processing image: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


